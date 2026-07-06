# Poller → Prometheus (Direct Write) → Grafana / CLI

> **Status:** Design / Planning  
> **Approach:** Prometheus Remote Write API — no scraping, no Pushgateway  
> **Date:** 2026-06-25  

---

## 1. The Core Idea

Instead of asking Prometheus to *scrape* an endpoint (pull model) or routing through a Pushgateway (extra process), the poller **writes metrics directly into Prometheus's TSDB** after every poll cycle using the **Remote Write protocol**.

```
BEFORE
──────
OpenSearch API
  + /proc  ──▶  poller.py  ──▶  metrics_YYYY-MM-DD.jsonl  ──▶  monitor CLI only


AFTER
─────
OpenSearch API                           ┌──▶  metrics_YYYY-MM-DD.jsonl  ──▶  monitor CLI (existing)
  + /proc  ──▶  poller.py  ─────────────┤
                                          └──▶  Prometheus TSDB (Remote Write)
                                                    │
                                                    ├──▶  monitor CLI  (PromQL via existing MetricsProvider)
                                                    └──▶  Grafana Dashboard (PromQL)
```

No extra process. No scraping. One Prometheus flag enabled. Data lands in TSDB the moment each poll cycle completes.

---

## 2. How Prometheus Remote Write Works

Prometheus exposes a `/api/v1/write` endpoint that accepts time-series data pushed **directly** into its TSDB. It must be enabled with a single startup flag:

```bash
prometheus --web.enable-remote-write-receiver
```

Once enabled, any client can POST time-series data to it. The protocol is:

```
POST http://localhost:9090/api/v1/write
Content-Type: application/x-protobuf
Content-Encoding: snappy
X-Prometheus-Remote-Write-Version: 0.1.0

Body: Snappy-compressed protobuf WriteRequest
```

The poller sends this POST after every poll cycle. Prometheus stores the data in its TSDB exactly as if it had scraped the metrics itself. Grafana and the monitor CLI both query it through the standard PromQL API — they don't care how data got in.

---

## 3. Python Library

We use [`prometheus-remote-writer`](https://pypi.org/project/prometheus-remote-writer/) — a lightweight PyPI package that handles the protobuf encoding and snappy compression internally.

```bash
pip install prometheus-remote-writer
```

Usage pattern:

```python
from prometheus_remote_writer import RemoteWriter

writer = RemoteWriter(url='http://localhost:9090/api/v1/write')

writer.send([
    {
        'metric': {
            '__name__': 'opensearch_node_cpu_percent',
            'job':      'hpe_opensearch_poller',
            'node':     'node-1',
        },
        'values':     [13.0],
        'timestamps': [1775740834000],  # milliseconds
    }
])
```

---

## 4. Prometheus Metrics Specification

All metrics use the prefix `opensearch_` to stay consistent with the PromQL queries already in `monitor/metrics_service.py`.

### 4.1 Per-Node Metrics — label: `node`

| Metric Name | Type | Unit | Source Field |
|---|---|---|---|
| `opensearch_node_cpu_percent` | Gauge | % | `nodes.<n>.cpu_pct` |
| `opensearch_node_heap_used_bytes` | Gauge | bytes | `nodes.<n>.heap_used_bytes` |
| `opensearch_node_heap_max_bytes` | Gauge | bytes | `nodes.<n>.heap_max_bytes` |
| `opensearch_node_heap_percent` | Gauge | % | `nodes.<n>.heap_pct` |
| `opensearch_node_disk_store_bytes` | Gauge | bytes | `nodes.<n>.disk_store_bytes` |
| `opensearch_node_disk_total_bytes` | Gauge | bytes | `nodes.<n>.disk_total_bytes` |
| `opensearch_node_disk_percent` | Gauge | % | `nodes.<n>.disk_pct` |
| `opensearch_node_index_total` | Counter | ops | `nodes.<n>.index_total` |
| `opensearch_node_gc_pause_rate_ms_per_s` | Gauge | ms/s | `nodes.<n>.gc_pause_rate_ms_per_s` |

### 4.2 Thread Pool Metrics — labels: `node`, `pool`

Pools tracked: `write`, `search`

| Metric Name | Type | Unit | Source Field |
|---|---|---|---|
| `opensearch_node_threadpool_queue` | Gauge | count | `nodes.<n>.thread_pool.<pool>.queue` |
| `opensearch_node_threadpool_active` | Gauge | count | `nodes.<n>.thread_pool.<pool>.active` |
| `opensearch_node_threadpool_rejected_per_s` | Gauge | ops/s | `nodes.<n>.tp_<pool>_rejected_per_s` |

### 4.3 Host / Process Metrics — no node label

| Metric Name | Type | Unit | Source Field |
|---|---|---|---|
| `opensearch_host_fd_count` | Gauge | count | `host.fd_count` |
| `opensearch_host_fd_limit` | Gauge | count | `host.fd_limit` |
| `opensearch_host_fd_percent` | Gauge | % | `host.fd_pct` |
| `opensearch_host_io_read_bps` | Gauge | bytes/s | `host.io_read_bps` |
| `opensearch_host_io_write_bps` | Gauge | bytes/s | `host.io_write_bps` |

---

## 5. Files to Create / Modify

### 5.1 `poller/storage/prometheus_writer.py`  ← NEW

The complete module. Replaces the old `writer.py` concept for Prometheus — JSONL writer is kept separately.

```python
"""
Prometheus Remote Write client for poller metrics.

Translates a fully-assembled poll record into time-series data points
and writes them directly into the Prometheus TSDB via the Remote Write API.

Requires Prometheus to be started with --web.enable-remote-write-receiver.

Call write_record(record) once per poll cycle, immediately after append_record().
Any failure is caught and logged — it never kills the poll loop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_remote_writer import RemoteWriter

from poller.config import (
    PROMETHEUS_REMOTE_WRITE_URL,
    PROMETHEUS_REMOTE_WRITE_JOB,
    PROMETHEUS_REMOTE_WRITE_ENABLED,
)

log = logging.getLogger(__name__)

# Module-level writer — reused across poll cycles
_writer: RemoteWriter | None = None


def _get_writer() -> RemoteWriter:
    global _writer
    if _writer is None:
        _writer = RemoteWriter(url=PROMETHEUS_REMOTE_WRITE_URL)
    return _writer


def write_record(record: dict[str, Any]) -> None:
    """
    Translate *record* (one poll cycle output) into Prometheus time-series
    and write them directly into the Prometheus TSDB via Remote Write.

    Parameters
    ----------
    record:
        Fully assembled dict with keys: ts, timestamp, nodes, host.
    """
    if not PROMETHEUS_REMOTE_WRITE_ENABLED:
        return

    try:
        series = _build_series(record)
        if series:
            _get_writer().send(series)
            log.debug("Remote write: pushed %d series to Prometheus", len(series))
    except Exception as exc:
        log.warning("Prometheus remote write failed (non-fatal): %s", exc)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _ts_ms(epoch_s: int) -> int:
    """Convert Unix epoch seconds to milliseconds (required by Remote Write)."""
    return epoch_s * 1000


def _base_labels(job: str) -> dict[str, str]:
    return {"job": job}


def _build_series(record: dict[str, Any]) -> list[dict]:
    """
    Convert the full poll record to a list of Remote Write series dicts.

    Each dict has the shape:
        {
            'metric':     { '__name__': '...', label_key: label_val, ... },
            'values':     [float],
            'timestamps': [int_ms],
        }
    """
    ts_ms    = _ts_ms(record["ts"])
    job      = PROMETHEUS_REMOTE_WRITE_JOB
    nodes    = record.get("nodes", {})
    host     = record.get("host",  {})
    series   = []

    base = _base_labels(job)

    # ── Per-node metrics ─────────────────────────────────────────────────────
    for node_name, snap in nodes.items():
        node_labels = {**base, "node": node_name}

        _add(series, ts_ms, node_labels, "opensearch_node_cpu_percent",
             snap.get("cpu_pct"))
        _add(series, ts_ms, node_labels, "opensearch_node_heap_used_bytes",
             snap.get("heap_used_bytes"))
        _add(series, ts_ms, node_labels, "opensearch_node_heap_max_bytes",
             snap.get("heap_max_bytes"))
        _add(series, ts_ms, node_labels, "opensearch_node_heap_percent",
             snap.get("heap_pct"))
        _add(series, ts_ms, node_labels, "opensearch_node_disk_store_bytes",
             snap.get("disk_store_bytes"))
        _add(series, ts_ms, node_labels, "opensearch_node_disk_total_bytes",
             snap.get("disk_total_bytes"))
        _add(series, ts_ms, node_labels, "opensearch_node_disk_percent",
             snap.get("disk_pct"))
        _add(series, ts_ms, node_labels, "opensearch_node_index_total",
             snap.get("index_total"))
        _add(series, ts_ms, node_labels, "opensearch_node_gc_pause_rate_ms_per_s",
             snap.get("gc_pause_rate_ms_per_s"))

        # ── Thread pool breakdown ─────────────────────────────────────────
        for pool, pool_data in snap.get("thread_pool", {}).items():
            pool_labels = {**node_labels, "pool": pool}
            _add(series, ts_ms, pool_labels, "opensearch_node_threadpool_queue",
                 pool_data.get("queue"))
            _add(series, ts_ms, pool_labels, "opensearch_node_threadpool_active",
                 pool_data.get("active"))
            rate_key = f"tp_{pool}_rejected_per_s"
            _add(series, ts_ms, pool_labels, "opensearch_node_threadpool_rejected_per_s",
                 snap.get(rate_key))

    # ── Host / process metrics ────────────────────────────────────────────────
    if host and not host.get("permission_error"):
        _add(series, ts_ms, base, "opensearch_host_fd_count",     host.get("fd_count"))
        _add(series, ts_ms, base, "opensearch_host_fd_limit",     host.get("fd_limit"))
        _add(series, ts_ms, base, "opensearch_host_fd_percent",   host.get("fd_pct"))
        _add(series, ts_ms, base, "opensearch_host_io_read_bps",  host.get("io_read_bps"))
        _add(series, ts_ms, base, "opensearch_host_io_write_bps", host.get("io_write_bps"))

    return series


def _add(
    series: list,
    ts_ms: int,
    labels: dict[str, str],
    metric_name: str,
    value: float | int | None,
) -> None:
    """Append one time-series entry only if value is present and finite."""
    if value is None:
        return
    try:
        v = float(value)
    except (TypeError, ValueError):
        return
    import math
    if not math.isfinite(v):
        return

    series.append({
        "metric":     {"__name__": metric_name, **labels},
        "values":     [v],
        "timestamps": [ts_ms],
    })
```

---

### 5.2 `poller/config.py`  ← MODIFY

Add these three config entries:

```python
# ─── Prometheus Remote Write ──────────────────────────────────────────────────
# Requires: prometheus --web.enable-remote-write-receiver
PROMETHEUS_REMOTE_WRITE_URL     = os.getenv(
    "PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write"
)
PROMETHEUS_REMOTE_WRITE_JOB     = os.getenv(
    "PROMETHEUS_REMOTE_WRITE_JOB", "hpe_opensearch_poller"
)
PROMETHEUS_REMOTE_WRITE_ENABLED = _env_bool(
    "PROMETHEUS_REMOTE_WRITE_ENABLED", True
)
```

---

### 5.3 `poller/poller.py`  ← MODIFY

In the persist block (~line 226), add one line:

```python
# ── Persist ───────────────────────────────────────────────────
written_path = append_record(output_dir, record)   # JSONL — unchanged
write_record(record)                                # Prometheus — new, non-fatal
```

Add at top of file:

```python
from poller.storage.prometheus_writer import write_record
```

---

### 5.4 `.env.example`  ← MODIFY

```dotenv
# Prometheus Remote Write (direct write to TSDB — no Pushgateway needed)
# Requires prometheus started with: --web.enable-remote-write-receiver
PROMETHEUS_REMOTE_WRITE_URL=http://localhost:9090/api/v1/write
PROMETHEUS_REMOTE_WRITE_JOB=hpe_opensearch_poller
PROMETHEUS_REMOTE_WRITE_ENABLED=true
```

---

### 5.5 `requirements.txt`  ← MODIFY

```
prometheus-remote-writer>=0.2.0
```

---

### 5.6 `monitor/metrics_service.py`  ← MODIFY (optional, adds CLI support)

The monitor CLI already has `_build_prometheus_series()` which issues PromQL range queries. The existing queries use metric names like `opensearch_os_cpu_percent` which come from the OpenSearch Prometheus exporter. We add a parallel method that queries **our** poller-written metric names:

```python
def _build_poller_prometheus_series(self, effective_tf: str) -> dict[str, TrendSeries]:
    """Query Prometheus for metrics written by the poller via Remote Write."""
    return {
        "cpu": self.fetch_prometheus_series(
            label="CPU",
            query='max_over_time(opensearch_node_cpu_percent{job="hpe_opensearch_poller"}[5m])',
            timeframe=effective_tf,
            unit="%",
        ),
        "heap": self.fetch_prometheus_series(
            label="JVM Heap",
            query='opensearch_node_heap_used_bytes{job="hpe_opensearch_poller"}',
            timeframe=effective_tf,
            unit="bytes",
        ),
        "indexing_rate": self.fetch_prometheus_series(
            label="Indexing Rate",
            query='rate(opensearch_node_index_total{job="hpe_opensearch_poller"}[1m])',
            timeframe=effective_tf,
            unit="ops/s",
        ),
    }
```

This method slots into the existing `auto` source-selection logic as a third candidate (after JSONL, before the exporter-based Prometheus queries).

---

## 6. Prometheus Setup

### One-Time Configuration Change

Add this flag when starting Prometheus:

```bash
# If running directly
prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-remote-write-receiver          # ← this is all that's needed

# If running via Docker
docker run -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-remote-write-receiver

# If running via systemd — add to /etc/default/prometheus or ExecStart:
ExecStart=/usr/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --web.enable-remote-write-receiver
```

**No changes to `prometheus.yml` are needed.** The poller pushes directly; Prometheus doesn't need a scrape job for this.

---

## 7. Grafana Dashboard — Panel Layout

`grafana/dashboards/opensearch_poller.json`

```
┌─────────────────────────────────────────────────────────────────────┐
│  ROW 1 — Cluster Health Snapshot                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │  CPU % / node    │  │  Heap % / node   │  │  Disk % (stat)    │  │
│  │  (time-series)   │  │  (time-series)   │  │  + store vs total │  │
│  └──────────────────┘  └──────────────────┘  └───────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 2 — Throughput & GC                                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐  │
│  │  Indexing Rate (ops/s)       │  │  GC Pause Rate (ms/s)        │  │
│  │  rate(index_total[1m])       │  │  per node — alert at 100     │  │
│  └──────────────────────────────┘  └──────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 3 — Thread Pool                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │  Write Queue     │  │  Search Queue    │  │  Rejection Rate   │  │
│  │  depth           │  │  depth           │  │  write + search   │  │
│  └──────────────────┘  └──────────────────┘  └───────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│  ROW 4 — Host Process                                                │
│  ┌───────────────────────────────┐  ┌──────────────────────────────┐ │
│  │  FD Count vs Limit            │  │  I/O Read / Write bps        │ │
│  │  gauge + time-series          │  │  time-series                 │ │
│  └───────────────────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Dashboard Variables:**

| Variable | Type | Query |
|---|---|---|
| `$node` | Label values | `label_values(opensearch_node_cpu_percent{job="hpe_opensearch_poller"}, node)` |
| `$interval` | Custom | Options: `1m`, `5m`, `15m`, `1h` |

---

## 8. PromQL Query Reference

### CPU

```promql
# Instant CPU % per node
opensearch_node_cpu_percent{job="hpe_opensearch_poller"}

# Smoothed 5-minute peak per node
max_over_time(opensearch_node_cpu_percent{job="hpe_opensearch_poller"}[$interval]) by (node)
```

### JVM Heap

```promql
# Heap used bytes
opensearch_node_heap_used_bytes{job="hpe_opensearch_poller"}

# Heap % (derived — more reliable than stored pct for alerting)
opensearch_node_heap_used_bytes / opensearch_node_heap_max_bytes * 100

# Smoothed heap %
avg_over_time(opensearch_node_heap_percent{job="hpe_opensearch_poller"}[$interval]) by (node)
```

### Disk

```promql
# Disk % used
opensearch_node_disk_percent{job="hpe_opensearch_poller"}

# Disk store growth rate (bytes/hour)
deriv(opensearch_node_disk_store_bytes{job="hpe_opensearch_poller"}[30m]) * 3600

# Estimated hours to full
(opensearch_node_disk_total_bytes - opensearch_node_disk_store_bytes)
  / clamp_min(deriv(opensearch_node_disk_store_bytes[1h]) * 3600, 1)
```

### Indexing

```promql
# Indexing rate — ops/s per node
rate(opensearch_node_index_total{job="hpe_opensearch_poller"}[1m]) by (node)

# Cluster-wide total indexing rate
sum(rate(opensearch_node_index_total{job="hpe_opensearch_poller"}[1m]))
```

### GC Pressure

```promql
# GC pause rate per node
opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller"}

# Alert threshold — highlight when > 100 ms/s
opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller"} > 100
```

### Thread Pool

```promql
# Write pool queue depth
opensearch_node_threadpool_queue{job="hpe_opensearch_poller", pool="write"}

# Search pool queue depth
opensearch_node_threadpool_queue{job="hpe_opensearch_poller", pool="search"}

# Active threads (both pools)
opensearch_node_threadpool_active{job="hpe_opensearch_poller"}

# Rejection rate — any pool
opensearch_node_threadpool_rejected_per_s{job="hpe_opensearch_poller"}
```

### File Descriptors

```promql
# FD count vs limit
opensearch_host_fd_count{job="hpe_opensearch_poller"}
opensearch_host_fd_limit{job="hpe_opensearch_poller"}

# FD exhaustion % (alert candidate > 80%)
opensearch_host_fd_count / opensearch_host_fd_limit * 100
```

### I/O

```promql
# Process-level I/O
opensearch_host_io_read_bps{job="hpe_opensearch_poller"}
opensearch_host_io_write_bps{job="hpe_opensearch_poller"}

# Combined throughput
opensearch_host_io_read_bps + opensearch_host_io_write_bps
```

---

## 9. Alerting Rules

`prometheus/hpe_monitor_alerts.yml`

```yaml
groups:
  - name: hpe_opensearch_poller
    rules:

      - alert: OpenSearchHighCPU
        expr: opensearch_node_cpu_percent{job="hpe_opensearch_poller"} > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.node }}"
          description: "CPU above 85% for 5 min (current: {{ $value }}%)"

      - alert: OpenSearchHeapCritical
        expr: >
          opensearch_node_heap_used_bytes{job="hpe_opensearch_poller"}
          / opensearch_node_heap_max_bytes{job="hpe_opensearch_poller"} * 100 > 90
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "JVM Heap critical on {{ $labels.node }}"
          description: "Heap at {{ $value }}% — OOM risk"

      - alert: OpenSearchGCPressure
        expr: opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller"} > 100
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "GC pressure on {{ $labels.node }}"
          description: "GC pause rate: {{ $value }} ms/s"

      - alert: OpenSearchThreadPoolRejections
        expr: opensearch_node_threadpool_rejected_per_s{job="hpe_opensearch_poller"} > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Thread pool rejections on {{ $labels.node }} pool={{ $labels.pool }}"
          description: "{{ $value }} rejections/s — indexing backpressure"

      - alert: OpenSearchFDExhaustion
        expr: opensearch_host_fd_count / opensearch_host_fd_limit * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "FD exhaustion warning"
          description: "{{ $value }}% of file descriptors in use"

      - alert: OpenSearchDiskGrowthRate
        expr: deriv(opensearch_node_disk_store_bytes{job="hpe_opensearch_poller"}[30m]) * 3600 > 1e9
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "OpenSearch disk growing fast on {{ $labels.node }}"
          description: "Disk growing at {{ $value | humanize }}B/hour"
```

---

## 10. Full Architecture Comparison

| Aspect | Old (JSONL) | Pushgateway | Remote Write (this doc) |
|---|---|---|---|
| **Extra processes** | None | Pushgateway daemon | None |
| **Prometheus config changes** | N/A | Add scrape job | Add one startup flag |
| **Data latency** | CLI reads files directly | Depends on scrape interval | Immediate on push |
| **Grafana support** | No | Yes | Yes |
| **Alertmanager support** | No | Yes | Yes |
| **Retention control** | Manual file rotation | Prometheus retention | Prometheus retention |
| **CLI fallback** | JSONL always available | PromQL via Prometheus | PromQL via Prometheus |
| **Dual-write (safety net)** | N/A | Yes (JSONL stays) | Yes (JSONL stays) |
| **Complexity** | Low | Medium | Low |

---

## 11. Quick-Start Checklist

```bash
# 1. Install the new dependency
pip install "prometheus-remote-writer>=0.2.0"
# (or update requirements.txt and re-install)

# 2. Enable Remote Write receiver in Prometheus
#    Add --web.enable-remote-write-receiver to your Prometheus startup command.
#    Then restart Prometheus.

# 3. Add to your .env
echo 'PROMETHEUS_REMOTE_WRITE_URL=http://localhost:9090/api/v1/write' >> .env
echo 'PROMETHEUS_REMOTE_WRITE_ENABLED=true' >> .env

# 4. Run the poller
python -m poller --interval 15

# 5. Verify data landed in Prometheus
curl 'http://localhost:9090/api/v1/query?query=opensearch_node_cpu_percent' | python3 -m json.tool

# 6. Import the Grafana dashboard
#    Grafana → Dashboards → Import → upload grafana/dashboards/opensearch_poller.json
#    Set datasource to your Prometheus instance.
```

---

## 12. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Remote Write vs Pushgateway** | Remote Write | No extra process, data lands in TSDB immediately, simpler operational model |
| **Dual-write (JSONL + Prometheus)** | Yes — keep JSONL | JSONL files serve as a longer archive and keep the existing CLI views working without changes |
| **Library for remote write** | `prometheus-remote-writer` | Handles protobuf encoding + snappy compression internally; minimal code in our repo |
| **Error handling** | Non-fatal catch-all | A Prometheus outage must never interrupt the core collection loop |
| **Timestamp unit** | Milliseconds | Required by the Remote Write protocol |
| **job label** | `hpe_opensearch_poller` | Namespaces our metrics from any other Prometheus jobs on the same server |
