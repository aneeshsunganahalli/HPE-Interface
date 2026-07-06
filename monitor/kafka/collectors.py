import datetime, subprocess, pathlib
import urllib3, requests, psutil
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from kafka import KafkaAdminClient, KafkaConsumer
    KAFKA_PY = True
except ImportError:
    KAFKA_PY = False

# ── Thresholds / metadata (used by display_utils + views) ─────
THRESHOLDS = {
    "K1": (30, 70), "K2": (40, 75), "K3": (99, 99),
    "K4": (50, 80), "K5": (50, 75), "K6": (25, 40),
    "K7": (0, 0),   "K8": (0, 0),   "K9": (99, 99),
}
INVERTED = {"K9", "K3"}
METRIC_META = {
    "K1": ("Health",     "Time-Based Consumer Lag",      "seconds behind"),
    "K2": ("Health",     "Message Throughput Ratio",     "prod/cons ratio"),
    "K3": ("Health",     "Under-Replicated Partitions",  "count"),
    "K4": ("Resource",   "Kafka Process CPU",            "%"),
    "K5": ("Resource",   "Kafka Process Memory",         "% of system RAM"),
    "K6": ("Resource",   "Kafka Total Disk Usage",       "% of root disk"),
    "K7": ("Throughput", "Messages Produced Rate",       "msgs/sec"),
    "K8": ("Throughput", "Messages Consumed Rate",       "msgs/sec"),
    "K9": ("Health",     "Active Broker Count",          "brokers"),
}
GROUP_COLORS = {"Health": "red", "Resource": "cyan", "Throughput": "yellow"}

# ── Prometheus helpers ─────────────────────────────────────────
def prom_instant(promql: str):
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query",
                         params={"query": promql},
                         auth=PROM_AUTH, verify=PROM_VERIFY, timeout=8)
        r.raise_for_status()
        res = r.json().get("data", {}).get("result", [])
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None

def prom_range(promql: str, minutes: int = 30) -> list:
    end   = int(__import__("time").time())
    start = end - minutes * 60
    step  = max(15, (minutes * 60) // 60)
    try:
        r = requests.get(f"{PROM_URL}/api/v1/query_range",
                         params={"query": promql, "start": start,
                                 "end": end, "step": f"{step}s"},
                         auth=PROM_AUTH, verify=PROM_VERIFY, timeout=10)
        r.raise_for_status()
        res = r.json().get("data", {}).get("result", [])
        return [(float(v[0]), float(v[1])) for v in res[0]["values"]] if res else []
    except Exception:
        return []

def find_kafka_proc():
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name    = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if ("java" in name or "java" in cmdline) and "kafka" in cmdline:
                if "zookeeper" not in cmdline and "console-consumer" not in cmdline:
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None
    
from monitor.config import (
    PROMETHEUS_HOST, PROMETHEUS_PORT, PROMETHEUS_SCHEME,
    OPENSEARCH_USER, OPENSEARCH_PASS,
)

PROM_URL    = f"{PROMETHEUS_SCHEME}://{PROMETHEUS_HOST}:{PROMETHEUS_PORT}"
PROM_AUTH   = (OPENSEARCH_USER, OPENSEARCH_PASS)
PROM_VERIFY = False

KAFKA_BOOTSTRAP = "localhost:9092"
KAFKA_TOPIC     = "test-topic"
KAFKA_GROUP     = "logstash-consumer-group"
KAFKA_LOG_DIR   = "/var/lib/kafka-logs"
KAFKA_BASE_DIR  = "/opt/kafka/kafka"

# ══════════════════════════════════════════════════════════════
#  COLLECTORS — K1 through K9
# ══════════════════════════════════════════════════════════════

# ── K1 : Time-Based Consumer Lag ─────────────────────────────
def collect_k1() -> dict:
    """
    How many SECONDS behind the consumer is.
    Formula: lag_messages / production_rate_msgs_per_sec
    Score  : 0s = 0  |  300s (5 min) = 100  |  capped at 100
    Source : kafka-python (live lag count) + Prometheus (rate)
    """
    lag_msgs = 0

    if KAFKA_PY:
        try:
            admin = KafkaAdminClient(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                request_timeout_ms=5000
            )
            consumer = KafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                request_timeout_ms=5000
            )
            committed = admin.list_consumer_group_offsets(KAFKA_GROUP)
            tps       = list(committed.keys())
            end_offs  = consumer.end_offsets(tps)
            lag_msgs  = sum(
                max(end_offs.get(tp, 0) - off.offset, 0)
                for tp, off in committed.items()
            )
            admin.close()
            consumer.close()
        except Exception:
            # Fallback to Prometheus if kafka-python call fails
            lag_msgs = prom_instant(
                f'sum(kafka_consumergroup_lag{{topic="{KAFKA_TOPIC}"}})'
            ) or 0
    else:
        lag_msgs = prom_instant(
            f'sum(kafka_consumergroup_lag{{topic="{KAFKA_TOPIC}"}})'
        ) or 0

    prod_rate = prom_instant(
        f'sum(rate(kafka_topic_partition_current_offset'
        f'{{topic="{KAFKA_TOPIC}"}}[60s]))'
    )
    prod_rate = max(prod_rate or 0.001, 0.001)
    lag_secs  = lag_msgs / prod_rate
    score     = round(min(lag_secs / 300.0, 1.0) * 100, 2)

    return {
        "value":     score,
        "lag_secs":  round(lag_secs,  2),
        "lag_msgs":  int(lag_msgs),
        "prod_rate": round(prod_rate, 4),
        "source":    "kafka-python" if KAFKA_PY else "prometheus-fallback",
    }


# ── K2 : Message Throughput Ratio ────────────────────────────
def collect_k2() -> dict:
    """
    prod_rate / cons_rate.
    Ratio 1.0 = perfectly balanced → score 0.
    Ratio 2.0+ = consumer severely behind → score 100.
    Score  : (ratio - 1.0) × 100, capped 0-100
    Source : Prometheus kafka_exporter
    """
    prod = prom_instant(
        f'sum(rate(kafka_topic_partition_current_offset'
        f'{{topic="{KAFKA_TOPIC}"}}[60s]))'
    ) or 0.0

    cons = prom_instant(
        f'sum(rate(kafka_consumergroup_current_offset'
        f'{{topic="{KAFKA_TOPIC}",consumergroup="{KAFKA_GROUP}"}}[60s]))'
    )
    cons  = max(cons or 0.001, 0.001)
    ratio = prod / cons
    score = round(min(max(ratio - 1.0, 0.0), 1.0) * 100, 2)

    return {
        "value":     score,
        "ratio":     round(ratio, 4),
        "prod_rate": round(prod,  4),
        "cons_rate": round(cons,  4),
    }


# ── K3 : Under-Replicated Partitions ─────────────────────────
def collect_k3() -> dict:
    """
    Count of partitions where not all replicas are in sync.
    Score  : 0 partitions = 100  |  any > 0 = 0  (zero tolerance)
    Source : Prometheus kafka_exporter
    """
    val   = prom_instant(
        f'sum(kafka_topic_partition_under_replicated_partition'
        f'{{topic="{KAFKA_TOPIC}"}})'
    )
    count = int(val) if val is not None else -1
    score = 100 if count == 0 else (0 if count > 0 else 50)
    return {
        "value": score,
        "count": count,
    }


# ── K4 : Kafka Process CPU % ──────────────────────────────────
def collect_k4() -> dict:
    """
    CPU % used by the Kafka JVM process specifically.
    Score  : direct mapping — cpu_pct IS the score (0-100)
    Source : psutil (process filter by cmdline)
    Note   : interval=1.0 means psutil blocks for 1 second to
             measure CPU accurately — this is intentional.
    """
    proc = find_kafka_proc()
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


# ── K5 : Kafka Process Memory ─────────────────────────────────
def collect_k5() -> dict:
    """
    RSS (Resident Set Size) of the Kafka JVM process.
    Score  : (rss_bytes / total_system_ram) * 100, × 2 scaling
             so 50% of system RAM consumed = score 100.
             This keeps the score meaningful on a 7.5 GiB system.
    Source : psutil (process filter)
    """
    proc = find_kafka_proc()
    if proc is None:
        return {
            "value":    0,
            "rss_mb":   None,
            "rss_pct":  None,
            "status":   "PROCESS NOT FOUND",
        }
    try:
        mem_info  = proc.memory_info()
        total_ram = psutil.virtual_memory().total
        rss_mb    = round(mem_info.rss / (1024**2), 2)
        rss_pct   = round((mem_info.rss / total_ram) * 100, 2)
        # Score: 50% of system RAM = 100 (aggressive threshold for 7.5 GiB system)
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


# ── K6 : Kafka Total Disk Usage ───────────────────────────────
def _du_bytes(path: str) -> int:
    """Return total bytes used by path via du -sb. Returns 0 on error."""
    try:
        result = subprocess.run(
            ["du", "-sb", path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    return 0


def collect_k6() -> dict:
    """
    Total disk footprint of entire Kafka installation vs root partition size.
    Includes BOTH the base install directory and the external data log directory.
    """
    try:
        # ── Measure both directories ──────────────────────────
        base_dir_bytes = _du_bytes(KAFKA_BASE_DIR)
        data_dir_bytes = _du_bytes(KAFKA_LOG_DIR)

        # ── Total Kafka installation footprint ────────────────
        kafka_total_bytes = base_dir_bytes + data_dir_bytes

        # ── Root partition stats ──────────────────────────────
        root            = psutil.disk_usage("/")
        root_total_gb   = round(root.total / (1024**3), 3)
        root_used_gb    = round(root.used  / (1024**3), 3)
        root_free_gb    = round(root.free  / (1024**3), 3)

        kafka_gb  = round(kafka_total_bytes / (1024**3), 3)
        kafka_pct = round((kafka_total_bytes / root.total) * 100, 2) if root.total > 0 else 0
        score     = round(min(kafka_pct, 100), 2)
        state     = ("SAFE"     if kafka_pct < 25 else
                     "WARNING"  if kafka_pct < 40 else
                     "CRITICAL")

        # ── Top-level component breakdown (from BASE_DIR) ─────
        applog_bytes = _du_bytes(f"{KAFKA_BASE_DIR}/logs")
        libs_bytes   = _du_bytes(f"{KAFKA_BASE_DIR}/libs")
        bin_bytes    = _du_bytes(f"{KAFKA_BASE_DIR}/bin")
        config_bytes = _du_bytes(f"{KAFKA_BASE_DIR}/config")
        
        # 'Other' is whatever is left in base_dir after subtracting the known folders
        other_bytes  = max(base_dir_bytes - applog_bytes - libs_bytes - bin_bytes - config_bytes, 0)

        # ── Inside KAFKA_LOG_DIR (Data) sub-breakdown ─────────
        msg_bytes    = 0
        kraft_bytes  = 0

        try:
            for item in pathlib.Path(KAFKA_LOG_DIR).iterdir():
                if item.name == "__cluster_metadata-0":
                    kraft_bytes += _du_bytes(str(item))
                elif item.is_dir():
                    msg_bytes += _du_bytes(str(item))
        except Exception:
            pass

        # Indexes and other metadata are whatever is left in the data_dir
        index_bytes = max(data_dir_bytes - msg_bytes - kraft_bytes, 0)

        # ── Combine for UI Presentation ───────────────────────
        # The UI shows a unified "logs/" folder. We combine app logs and data logs here.
        logs_bytes = applog_bytes + data_dir_bytes

        def gb(b): return round(b / (1024**3), 3)

        return {
            "value":          score,
            "kafka_pct":      kafka_pct,
            "kafka_gb":       kafka_gb,
            "root_total_gb":  root_total_gb,
            "root_used_gb":   root_used_gb,
            "root_free_gb":   root_free_gb,
            "state":          state,
            # component breakdown
            "logs_gb":        gb(logs_bytes),
            "libs_gb":        gb(libs_bytes),
            "bin_gb":         gb(bin_bytes),
            "config_gb":      gb(config_bytes),
            "other_gb":       gb(other_bytes),
            # logs sub-breakdown
            "msg_gb":         gb(msg_bytes),
            "index_gb":       gb(index_bytes),
            "kraft_gb":       gb(kraft_bytes),
            "applog_gb":      gb(applog_bytes),
        }
    except Exception as e:
        return {
            "value":     0,
            "kafka_pct": None,
            "state":     "ERROR",
            "error":     str(e),
        }


# ── K7 : Messages Produced Rate ──────────────────────────────
def collect_k7() -> dict:
    """
    Current messages-per-second production rate.
    Informational — no score threshold, raw rate displayed.
    Source : Prometheus kafka_exporter rate()
    """
    rate = prom_instant(
        f'sum(rate(kafka_topic_partition_current_offset'
        f'{{topic="{KAFKA_TOPIC}"}}[60s]))'
    )
    return {
        "value": round(rate, 4) if rate is not None else None,
        "unit":  "msgs/sec",
    }


# ── K8 : Messages Consumed Rate ──────────────────────────────
def collect_k8() -> dict:
    """
    Current messages-per-second consumption rate by Logstash.
    Informational — shown alongside K7 to visualize the gap.
    Source : Prometheus kafka_exporter rate()
    """
    rate = prom_instant(
        f'sum(rate(kafka_consumergroup_current_offset'
        f'{{topic="{KAFKA_TOPIC}",consumergroup="{KAFKA_GROUP}"}}[60s]))'
    )
    return {
        "value": round(rate, 4) if rate is not None else None,
        "unit":  "msgs/sec",
    }


# ── K9 : Active Broker Count ─────────────────────────────────
def collect_k9() -> dict:
    """
    Number of active Kafka brokers.
    Score  : 1+ broker = 100  |  0 brokers = 0  (hard gate)
    Source : Prometheus kafka_exporter
    """
    val   = prom_instant("kafka_brokers")
    count = int(val) if val is not None else 0
    score = 100 if count >= 1 else 0
    return {
        "value": score,
        "count": count,
    }


# ══════════════════════════════════════════════════════════════
#  MASTER COLLECTOR
#  Call this once to get all 9 metrics in one pass.
# ══════════════════════════════════════════════════════════════

def collect_all() -> dict:
    """
    Collect all 9 Kafka metrics in one pass.
    K4 blocks for 1 second (CPU measurement interval) — this is
    intentional and gives accurate CPU readings.
    """
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "K1": collect_k1(),
        "K2": collect_k2(),
        "K3": collect_k3(),
        "K4": collect_k4(),
        "K5": collect_k5(),
        "K6": collect_k6(),
        "K7": collect_k7(),
        "K8": collect_k8(),
        "K9": collect_k9(),
    }