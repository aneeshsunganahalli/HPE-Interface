"""
Prometheus self-monitoring collectors — P1 through P13.

Mirrors the Kafka collector pattern (monitor/kafka/collectors.py):
  - Each collect_pN() returns a dict with at minimum {"value": score, ...}
  - collect_all() runs every collector in one pass with optimizations:
      • /metrics text is fetched ONCE and shared across P3, P4, P8, P9, P12
      • P6 (disk I/O) and P7 (network I/O) share a single 1-second sample window
      • P1 CPU measurement uses a 1-second interval (unavoidable for accuracy)
  - METRIC_META / THRESHOLDS / GROUP_COLORS drive the display layer.

Data Sources:
  - psutil          → process CPU, memory, disk, I/O, network
  - /metrics        → Prometheus own exposition endpoint (text format)
  - Prometheus API  → PromQL instant queries for rate-based metrics
"""

import datetime
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psutil
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from monitor.config import (
    PROMETHEUS_HOST,
    PROMETHEUS_PORT,
    PROMETHEUS_SCHEME,
    PROMETHEUS_DATA_DIR,
)

# ── Connection config ─────────────────────────────────────────
PROM_URL    = f"{PROMETHEUS_SCHEME}://{PROMETHEUS_HOST}:{PROMETHEUS_PORT}"
PROM_VERIFY = False

# ── Thresholds / metadata (used by display_utils + views) ─────
THRESHOLDS = {
    "P1":  (70, 90),   # CPU %
    "P2":  (50, 75),   # Memory score (rss_pct × 2)
    "P3":  (0, 0),     # Uptime — informational
    "P4":  (60, 80),   # Open FD ratio %
    "P5":  (70, 85),   # Disk usage %
    "P6":  (0, 0),     # Disk I/O — informational
    "P7":  (0, 0),     # Network — informational
    "P8":  (0, 0),     # Head series — informational
    "P9":  (0, 0),     # Head chunks — informational
    "P10": (0, 0),     # Samples/sec — informational
    "P11": (0, 0),     # Storage size — informational
    "P12": (500, 2000),  # Query latency ms
    "P13": (0, 0),     # Active queries — informational
}

INVERTED: set[str] = set()  # No inverted metrics for Prometheus

METRIC_META = {
    "P1":  ("Process",   "CPU Usage",                "%"),
    "P2":  ("Process",   "Memory Usage",             "MB"),
    "P3":  ("Process",   "Process Uptime",           "duration"),
    "P4":  ("Process",   "Open File Descriptors",    "ratio"),
    "P5":  ("System",    "Disk Usage",               "%"),
    "P6":  ("System",    "Disk I/O",                 "MB/s"),
    "P7":  ("System",    "Network Traffic",          "MB/s"),
    "P8":  ("TSDB",      "Head Series",              "count"),
    "P9":  ("TSDB",      "Head Chunks",              "count"),
    "P10": ("TSDB",      "Samples Appended/sec",     "samples/s"),
    "P11": ("TSDB",      "Storage Size",             "GB"),
    "P12": ("Query",     "Query Latency (p99)",      "ms"),
    "P13": ("Query",     "Active Queries",           "count"),
}

GROUP_COLORS = {
    "Process": "cyan",
    "System":  "magenta",
    "TSDB":    "yellow",
    "Query":   "green",
}

# Keys that are purely informational (no 0-100 score bar)
INFORMATIONAL = {"P3", "P6", "P7", "P8", "P9", "P10", "P11", "P13"}


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _prom_metrics_text() -> str:
    """Fetch raw /metrics exposition text from Prometheus."""
    try:
        r = requests.get(
            f"{PROM_URL}/metrics",
            verify=PROM_VERIFY,
            timeout=8,
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


def _parse_metric(text: str, name: str) -> float | None:
    """
    Extract the first numeric value for a metric name from exposition text.
    Handles both bare metrics (name VALUE) and metrics with labels (name{...} VALUE).
    """
    # First try bare metric (no labels)
    pattern = re.compile(rf"^{re.escape(name)}\s+([\d.eE+\-]+)", re.MULTILINE)
    m = pattern.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # Fallback: metric with any labels
    pattern_labels = re.compile(rf"^{re.escape(name)}\{{[^}}]*\}}\s+([\d.eE+\-]+)", re.MULTILINE)
    m = pattern_labels.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _parse_metric_with_labels(text: str, name: str, labels: dict[str, str]) -> float | None:
    """
    Extract metric value matching specific label key=value pairs.
    Labels are matched individually (order-independent).
    """
    # Find all lines matching the metric name with labels
    pattern = re.compile(
        rf'^{re.escape(name)}\{{([^}}]*)\}}\s+([\d.eE+\-]+)',
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        label_str = match.group(1)
        value_str = match.group(2)
        # Check that ALL requested labels are present in this line
        all_match = True
        for k, v in labels.items():
            if f'{k}="{v}"' not in label_str:
                all_match = False
                break
        if all_match:
            try:
                return float(value_str)
            except ValueError:
                continue
    return None


def _parse_all_metric_values(text: str, name: str) -> list[float]:
    """Extract ALL numeric values for a metric name (all label combinations)."""
    values = []
    pattern = re.compile(
        rf'^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([\d.eE+\-]+)',
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            continue
    return values


def _prom_instant(promql: str) -> float | None:
    """Run an instant PromQL query against the Prometheus API."""
    try:
        r = requests.get(
            f"{PROM_URL}/api/v1/query",
            params={"query": promql},
            verify=PROM_VERIFY,
            timeout=8,
        )
        r.raise_for_status()
        res = r.json().get("data", {}).get("result", [])
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None


def find_prometheus_proc():
    """Find the Prometheus server process via psutil."""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name    = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if "prometheus" in name or "prometheus" in cmdline:
                # Exclude node_exporter, alertmanager, pushgateway, etc.
                excludes = ("node_exporter", "alertmanager", "pushgateway",
                            "blackbox_exporter", "snmp_exporter")
                if not any(ex in cmdline for ex in excludes):
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _du_bytes(path: str) -> int:
    """Return total bytes used by path via du -sb. Returns 0 on error."""
    try:
        result = subprocess.run(
            ["du", "-sb", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    return 0


def _format_uptime(seconds: float) -> str:
    """Convert seconds to a human-readable duration string."""
    if seconds < 0:
        return "N/A"
    days    = int(seconds // 86400)
    hours   = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _sample_io_and_net() -> tuple[dict, dict]:
    """
    Sample disk I/O and network counters over a single 1-second window.
    Returns (p6_result, p7_result) — avoids two separate 1-second sleeps.
    """
    try:
        io1  = psutil.disk_io_counters()
        net1 = psutil.net_io_counters()
        time.sleep(1)
        io2  = psutil.disk_io_counters()
        net2 = psutil.net_io_counters()

        p6 = {
            "value":     None,
            "read_mbs":  round((io2.read_bytes - io1.read_bytes) / (1024**2), 2),
            "write_mbs": round((io2.write_bytes - io1.write_bytes) / (1024**2), 2),
        }
        p7 = {
            "value":    None,
            "recv_mbs": round((net2.bytes_recv - net1.bytes_recv) / (1024**2), 2),
            "sent_mbs": round((net2.bytes_sent - net1.bytes_sent) / (1024**2), 2),
        }
        return p6, p7
    except Exception as e:
        err = str(e)
        return (
            {"value": None, "read_mbs": None, "write_mbs": None, "error": err},
            {"value": None, "recv_mbs": None, "sent_mbs": None, "error": err},
        )




# ── P1 : Prometheus Process CPU % ─────────────────────────────
def collect_p1(proc=None) -> dict:
    """
    CPU % used by the Prometheus process.
    Score  : direct mapping — cpu_pct IS the score (0-100)
    Source : psutil (process filter by cmdline)
    Note   : interval=1.0 means psutil blocks for 1 second.
    """
    if proc is None:
        proc = find_prometheus_proc()
    if proc is None:
        return {
            "value":   0,
            "cpu_pct": None,
            "pid":     None,
            "status":  "PROCESS NOT FOUND",
        }
    try:
        cpu_pct = proc.cpu_percent(interval=1.0)
        return {
            "value":   round(min(cpu_pct, 100), 2),
            "cpu_pct": round(cpu_pct, 2),
            "pid":     proc.pid,
            "status":  "running",
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return {
            "value":   0,
            "cpu_pct": None,
            "pid":     None,
            "status":  f"ERROR: {e}",
        }


# ── P2 : Prometheus Process Memory ───────────────────────────
def collect_p2(proc=None) -> dict:
    """
    RSS (Resident Set Size) of the Prometheus process.
    Score  : (rss_bytes / total_system_ram) * 100, × 2 scaling
    Source : psutil (process filter)
    """
    if proc is None:
        proc = find_prometheus_proc()
    if proc is None:
        return {
            "value":   0,
            "rss_mb":  None,
            "rss_pct": None,
            "status":  "PROCESS NOT FOUND",
        }
    try:
        mem_info  = proc.memory_info()
        total_ram = psutil.virtual_memory().total
        rss_mb    = round(mem_info.rss / (1024**2), 2)
        rss_pct   = round((mem_info.rss / total_ram) * 100, 2)
        score     = round(min(rss_pct * 2.0, 100), 2)
        return {
            "value":        score,
            "rss_mb":       rss_mb,
            "rss_pct":      rss_pct,
            "total_ram_gb": round(total_ram / (1024**3), 2),
            "pid":          proc.pid,
            "status":       "running",
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return {
            "value":   0,
            "rss_mb":  None,
            "rss_pct": None,
            "status":  f"ERROR: {e}",
        }


# ── P3 : Process Uptime ──────────────────────────────────────
def collect_p3(metrics_text: str | None = None) -> dict:
    """
    Time since Prometheus last restarted.
    Source : /metrics → process_start_time_seconds
    """
    text = metrics_text if metrics_text is not None else _prom_metrics_text()
    start_ts = _parse_metric(text, "process_start_time_seconds")
    if start_ts is not None:
        uptime_secs = time.time() - start_ts
        return {
            "value":       None,  # informational
            "uptime_secs": round(uptime_secs, 0),
            "uptime_str":  _format_uptime(uptime_secs),
            "start_ts":    start_ts,
        }
    return {
        "value":       None,
        "uptime_secs": None,
        "uptime_str":  "unavailable",
        "start_ts":    None,
    }


# ── P4 : Open File Descriptors ───────────────────────────────
def collect_p4(metrics_text: str | None = None) -> dict:
    """
    Ratio of open FDs to max allowed FDs.
    Score  : (open / max) * 100
    Source : /metrics → process_open_fds, process_max_fds
    """
    text = metrics_text if metrics_text is not None else _prom_metrics_text()
    open_fds = _parse_metric(text, "process_open_fds")
    max_fds  = _parse_metric(text, "process_max_fds")

    if open_fds is not None and max_fds is not None and max_fds > 0:
        ratio = round((open_fds / max_fds) * 100, 2)
        return {
            "value":    ratio,
            "open_fds": int(open_fds),
            "max_fds":  int(max_fds),
        }
    return {
        "value":    0,
        "open_fds": int(open_fds) if open_fds is not None else None,
        "max_fds":  int(max_fds) if max_fds is not None else None,
    }


# ── P5 : Disk Usage (%) ──────────────────────────────────────
def collect_p5() -> dict:
    """
    Disk usage of the partition hosting the Prometheus TSDB data dir.
    Score  : disk usage percentage (0–100)
    Source : psutil.disk_usage on PROMETHEUS_DATA_DIR
    Falls back to root partition if PROMETHEUS_DATA_DIR doesn't exist.
    """
    # Try configured path first, then common alternatives, then root
    candidates = [PROMETHEUS_DATA_DIR]
    if PROMETHEUS_DATA_DIR != "/":
        candidates.extend([
            "/var/lib/prometheus",
            "/opt/prometheus/data",
            "/prometheus",
            "/",
        ])
    for path in candidates:
        try:
            import os
            if not os.path.exists(path):
                continue
            usage = psutil.disk_usage(path)
            pct = round(usage.percent, 2)
            return {
                "value":       pct,
                "disk_pct":    pct,
                "used_gb":     round(usage.used / (1024**3), 3),
                "total_gb":    round(usage.total / (1024**3), 3),
                "free_gb":     round(usage.free / (1024**3), 3),
                "path":        path,
            }
        except Exception:
            continue
    # Absolute fallback to root
    try:
        usage = psutil.disk_usage("/")
        pct = round(usage.percent, 2)
        return {
            "value":       pct,
            "disk_pct":    pct,
            "used_gb":     round(usage.used / (1024**3), 3),
            "total_gb":    round(usage.total / (1024**3), 3),
            "free_gb":     round(usage.free / (1024**3), 3),
            "path":        "/ (fallback)",
        }
    except Exception as e:
        return {
            "value":    0,
            "disk_pct": None,
            "error":    str(e),
            "path":     PROMETHEUS_DATA_DIR,
        }


# ── P6 : Disk I/O ────────────────────────────────────────────
def collect_p6() -> dict:
    """
    System-wide disk read/write rate (snapshot).
    Source : psutil.disk_io_counters (1-second sample)
    """
    p6, _ = _sample_io_and_net()
    return p6


# ── P7 : Network Traffic ─────────────────────────────────────
def collect_p7() -> dict:
    """
    System-wide network I/O rate (snapshot).
    Source : psutil.net_io_counters (1-second sample)
    """
    _, p7 = _sample_io_and_net()
    return p7


# ── P8 : Head Series ─────────────────────────────────────────
def collect_p8(metrics_text: str | None = None) -> dict:
    """
    Active time series count in TSDB head block.
    Source : /metrics → prometheus_tsdb_head_series
    """
    text = metrics_text if metrics_text is not None else _prom_metrics_text()
    val = _parse_metric(text, "prometheus_tsdb_head_series")
    return {
        "value": None,  # informational
        "count": int(val) if val is not None else None,
    }


# ── P9 : Head Chunks ─────────────────────────────────────────
def collect_p9(metrics_text: str | None = None) -> dict:
    """
    Active chunks in memory in the TSDB head block.
    Source : /metrics → prometheus_tsdb_head_chunks
    """
    text = metrics_text if metrics_text is not None else _prom_metrics_text()
    val = _parse_metric(text, "prometheus_tsdb_head_chunks")
    return {
        "value": None,  # informational
        "count": int(val) if val is not None else None,
    }


# ── P10 : Samples Appended/sec ───────────────────────────────
def collect_p10() -> dict:
    """
    Rate of samples being appended to the TSDB.
    Source : Prometheus API → rate(prometheus_tsdb_head_samples_appended_total[1m])
    Falls back to the counter value if rate query returns nothing.
    """
    rate = _prom_instant(
        "rate(prometheus_tsdb_head_samples_appended_total[1m])"
    )
    if rate is None:
        # Fallback: try the raw counter (user sees total, not rate)
        rate = _prom_instant("prometheus_tsdb_head_samples_appended_total")
        if rate is not None:
            return {
                "value": None,
                "rate":  None,
                "total": round(rate, 0),
                "unit":  "samples/s",
                "note":  "rate unavailable, showing total appended",
            }
    return {
        "value": None,  # informational
        "rate":  round(rate, 2) if rate is not None else None,
        "unit":  "samples/s",
    }


# ── P11 : Storage Size (GB) ──────────────────────────────────
def collect_p11() -> dict:
    """
    Total disk footprint of the Prometheus TSDB data directory.
    Source : du -sb on PROMETHEUS_DATA_DIR
    Tries common paths if configured dir doesn't exist.
    """
    import os
    candidates = [PROMETHEUS_DATA_DIR]
    if PROMETHEUS_DATA_DIR != "/":
        candidates.extend([
            "/var/lib/prometheus",
            "/opt/prometheus/data",
            "/prometheus",
        ])
    for path in candidates:
        if os.path.exists(path):
            total_bytes = _du_bytes(path)
            total_gb = round(total_bytes / (1024**3), 3)
            return {
                "value":         None,  # informational
                "storage_gb":    total_gb,
                "storage_bytes": total_bytes,
                "path":          path,
            }
    return {
        "value":         None,
        "storage_gb":    0,
        "storage_bytes": 0,
        "path":          f"{PROMETHEUS_DATA_DIR} (not found)",
    }


# ── P12 : Query Latency (p99) ────────────────────────────────
def collect_p12(metrics_text: str | None = None) -> dict:
    """
    99th percentile query engine latency.
    Score  : latency_ms mapped to 0–100 via thresholds
    Source : /metrics → prometheus_engine_query_duration_seconds
    """
    text = metrics_text if metrics_text is not None else _prom_metrics_text()

    val = None

    # Strategy 1: quantile="0.99" with slice="inner_eval"
    if val is None:
        val = _parse_metric_with_labels(
            text,
            "prometheus_engine_query_duration_seconds",
            {"slice": "inner_eval", "quantile": "0.99"},
        )

    # Strategy 2: any quantile="0.99"
    if val is None:
        val = _parse_metric_with_labels(
            text,
            "prometheus_engine_query_duration_seconds",
            {"quantile": "0.99"},
        )

    # Strategy 3: max across ALL reported quantiles/slices
    if val is None:
        all_vals = _parse_all_metric_values(
            text, "prometheus_engine_query_duration_seconds"
        )
        if all_vals:
            val = max(all_vals)

    # Strategy 4: try PromQL API as last resort
    if val is None:
        val = _prom_instant(
            'max(prometheus_engine_query_duration_seconds{quantile="0.99"})'
        )

    if val is not None:
        latency_ms = round(val * 1000, 2)
        warn, crit = THRESHOLDS["P12"]
        if latency_ms <= warn:
            score = round((latency_ms / warn) * 50, 2) if warn > 0 else 0
        else:
            score = round(50 + ((latency_ms - warn) / max(crit - warn, 1)) * 50, 2)
        score = round(min(score, 100), 2)
        return {
            "value":      score,
            "latency_ms": latency_ms,
        }
    return {
        "value":      0,
        "latency_ms": None,
    }


# ── P13 : Active Queries ─────────────────────────────────────
def collect_p13() -> dict:
    """
    Current number of concurrent queries being executed.
    Source : Prometheus API → prometheus_engine_queries
    """
    val = _prom_instant("prometheus_engine_queries")
    if val is None:
        # Fallback: try the /metrics exposition text
        text = _prom_metrics_text()
        val = _parse_metric(text, "prometheus_engine_queries")
    return {
        "value": None,  # informational
        "count": int(val) if val is not None else 0,
    }



def collect_all() -> dict:
    """
    Collect all 13 Prometheus self-monitoring metrics in one pass.

    Optimizations over naive sequential collection:
      1. /metrics text is fetched ONCE and reused by P3, P4, P8, P9, P12.
      2. Disk I/O (P6) and Network I/O (P7) share a single 1-second sample.
      3. CPU sampling (P1, 1s) runs IN PARALLEL with the I/O sampling (P6+P7, 1s)
         via a thread pool — total wall-clock ~1 second instead of ~3 seconds.
    """
    # ── Phase 0: Find the Prometheus process once ─────────────
    proc = find_prometheus_proc()

    # ── Phase 1: Kick off blocking work in parallel ───────────
    #   Thread A: CPU sampling (1 second)
    #   Thread B: Disk + Network I/O sampling (1 second, combined)
    #   Main thread: fetch /metrics text + instant queries (non-blocking)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cpu_future = pool.submit(collect_p1, proc)
        io_future  = pool.submit(_sample_io_and_net)

        # While threads sleep for 1s, do all the non-blocking work
        metrics_text = _prom_metrics_text()

        p2  = collect_p2(proc)
        p3  = collect_p3(metrics_text)
        p4  = collect_p4(metrics_text)
        p5  = collect_p5()
        p8  = collect_p8(metrics_text)
        p9  = collect_p9(metrics_text)
        p10 = collect_p10()
        p11 = collect_p11()
        p12 = collect_p12(metrics_text)
        p13 = collect_p13()

        # ── Phase 2: Collect thread results ───────────────────
        p1 = cpu_future.result()
        p6, p7 = io_future.result()

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "P1":  p1,
        "P2":  p2,
        "P3":  p3,
        "P4":  p4,
        "P5":  p5,
        "P6":  p6,
        "P7":  p7,
        "P8":  p8,
        "P9":  p9,
        "P10": p10,
        "P11": p11,
        "P12": p12,
        "P13": p13,
    }
