# Monitor Module Walkthrough (Mentor Guide)

This document is for walking mentors through the `monitor/` folder only, with a complete list of metric formulas used by the OpenSearch monitor views.

## 1) What The `monitor/` Module Does

The `monitor/` package is the CLI dashboard layer for OpenSearch operations.

It provides:
- Service entry and menu navigation (`monitor/cli.py`, `monitor/menus.py`)
- OpenSearch data access (`monitor/client.py`)
- Metrics backend routing and trend aggregation (`monitor/metrics_service.py`, `monitor/poller_history.py`)
- User-facing operational views (`monitor/Opensearch/views/*.py`)
- Shared formatting, thresholds, and helpers (`monitor/utils.py`, `monitor/config.py`)

## 2) High-Level Runtime Flow

1. `monitor/cli.py`
- Parses CLI flags (`--timeframe`, `--spike-ts`, `--metrics-source`)
- Selects service (OpenSearch currently active)

2. `monitor/menus.py`
- Routes user choice to one of the OpenSearch views:
  - Quick Summary
  - Cluster Health
  - Index Deep Dive
  - Node Performance
  - Shard Overview
  - Data Streams
  - Historical Trends
  - Log Browser
  - Root Cause Analysis

3. `monitor/Opensearch/views/*.py`
- Calls fetch helpers from `monitor/client.py`
- Computes derived metrics and status symbols
- Renders Rich panels/tables for operator readability

4. `monitor/client.py`
- Centralizes all OpenSearch API requests
- Delegates trend/timeframe logic to `metrics_service` where needed

5. `monitor/metrics_service.py` + `monitor/poller_history.py`
- Chooses poller vs Prometheus trend source
- Builds normalized trend series used by Historical Trends view

## 3) File-by-File Walkthrough Notes

### `monitor/client.py`
- Single integration point for OpenSearch API calls.
- Important for explaining separation of concerns: views do not build request bodies directly except through these helpers.
- Includes log analytics queries (`search_logs`, `fetch_error_summary`, `fetch_log_rate`, `fetch_logs_for_spike`).

### `monitor/metrics_service.py`
- Core metrics router and trend normalizer.
- For historical charts:
  - Poller path: consumes JSONL snapshots from poller output.
  - Prometheus path: runs PromQL (`max_over_time`, `sum(rate(...))`).
  - Auto mode: per metric key, uses poller first, Prometheus fallback.
- Collapses multi-series Prometheus responses into one line using max-per-timestamp.

### `monitor/poller_history.py`
- Reads `poller/data/metrics_YYYY-MM-DD.jsonl`.
- Buckets samples into fixed 5-minute windows by default.
- Produces trend buckets for:
  - CPU (max in bucket)
  - Heap used bytes (max in bucket)
  - Indexing rate (delta counter / elapsed seconds, then max in bucket)

### `monitor/Opensearch/views/quick_summary.py`
- 10-second operational snapshot.
- Uses cluster-wide aggregates from `/_cluster/stats` plus per-node warnings.
- Main derived metrics: heap %, disk %, total data size, shard state counts.

### `monitor/Opensearch/views/node_performance.py`
- Node-by-node CPU, heap, system RAM, disk pressure.
- Adds diagnostics by combining threshold pressure with Performance Analyzer signals.

### `monitor/Opensearch/views/trends.py`
- Historical chart rendering for CPU, heap, indexing rate.
- Computes chart normalization, average, and narrative readout conditions.

### `monitor/Opensearch/views/data_streams.py`
- Data stream freshness and staleness classification from latest timestamp.
- Computes stream age in minutes/hours/days and pipeline alert severity.

### `monitor/Opensearch/views/cluster_health.py`, `index_deep_dive.py`, `shard_overview.py`, `log_browser.py`, `root_cause.py`
- Mostly formatting and operational interpretation.
- Derived computations are primarily counts, formatting, grouping, and time-window construction.

## 4) Complete OpenSearch Metric Formula Catalog

Below is every formula used in `monitor/` for OpenSearch metric computation.

### A) Resource and Capacity Metrics

1. JVM heap utilization percentage (per node)
- Formula: `heap_pct = (heap_used / heap_max) * 100` (if `heap_max > 0`, else `0`)
- Used in:
  - `monitor/Opensearch/views/node_performance.py`
  - `monitor/Opensearch/views/quick_summary.py` (node warnings)

2. Cluster heap utilization percentage (cluster total)
- Formula: `heap_pct_total = (heap_used_total / heap_max_total) * 100` (if denominator > 0, else `0`)
- Used in: `monitor/Opensearch/views/quick_summary.py`

3. Disk used bytes (cluster)
- Formula: `disk_used_total = fs_total - fs_available`
- Used in: `monitor/Opensearch/views/quick_summary.py`

4. Disk utilization percentage (cluster)
- Formula: `disk_pct_total = (disk_used_total / disk_total_total) * 100` (if denominator > 0, else `0`)
- Used in: `monitor/Opensearch/views/quick_summary.py`

5. Disk used bytes (per node)
- Formula: `disk_used = disk_total - disk_avail`
- Used in: `monitor/Opensearch/views/node_performance.py`

6. Disk utilization percentage (per node)
- Formula: `disk_pct = (disk_used / disk_total) * 100` (if denominator > 0, else `0`)
- Used in:
  - `monitor/Opensearch/views/node_performance.py`
  - `monitor/Opensearch/views/quick_summary.py` (from `/_cat/allocation` parsed values)

7. Total index data size
- Formula: `total_data = sum(parse_size_string(index.store.size) for each index)`
- Used in: `monitor/Opensearch/views/quick_summary.py`

8. Total data stream storage
- Formula: `total_size = sum(stream_size_bytes for each stream)`
- Used in: `monitor/Opensearch/views/data_streams.py`

9. Size string to bytes conversion
- Formula: `bytes = numeric_value * unit_multiplier`
- Multipliers: `kb=1024`, `mb=1024^2`, `gb=1024^3`, `tb=1024^4`, `pb=1024^5`
- Used in: `monitor/utils.py` via `parse_size_string`

### B) Trend and Time-Series Metrics

10. Poller indexing rate (counter derivative)
- Formula:
  - `delta = current_index_total - previous_index_total`
  - `elapsed = max(1, current_ts - previous_ts)`
  - `rate = delta / elapsed` if `delta >= 0`, else `0`
- Unit: ops/sec
- Used in: `monitor/poller_history.py`

11. Poller bucket aggregation (CPU)
- Formula per bucket: `cpu_bucket_value = max(cpu_pct samples in bucket)`
- Used in: `monitor/poller_history.py`

12. Poller bucket aggregation (Heap)
- Formula per bucket: `heap_bucket_value = max(heap_used_bytes samples in bucket)`
- Used in: `monitor/poller_history.py`

13. Poller bucket aggregation (Indexing rate)
- Formula per bucket: `indexing_rate_bucket = max(rate samples in bucket)`
- Used in: `monitor/poller_history.py`

14. Cluster-level poller CPU point
- Formula: `cpu_pct_point = max(node.cpu_pct over nodes in snapshot)`
- Used in: `monitor/poller_history.py`

15. Cluster-level poller heap point
- Formula: `heap_used_point = max(node.heap_used_bytes over nodes in snapshot)`
- Used in: `monitor/poller_history.py`

16. Cluster-level poller indexing counter point
- Formula: `index_total_point = sum(node.index_total over nodes with value)`
- Used in: `monitor/poller_history.py`

17. Prometheus CPU trend query
- Formula (PromQL): `max_over_time(opensearch_os_cpu_percent[5m])`
- Used in: `monitor/metrics_service.py`

18. Prometheus heap trend query
- Formula (PromQL): `max_over_time(opensearch_jvm_mem_heap_used_bytes[5m])`
- Used in: `monitor/metrics_service.py`

19. Prometheus indexing-rate trend query
- Formula (PromQL): `sum(rate(opensearch_indices_indexing_index_total[5m]))`
- Fallback formula: `sum(rate(opensearch_indices_indexing_index_count[5m]))`
- Used in: `monitor/metrics_service.py`

20. Prometheus series collapse to single line
- Formula per timestamp bucket: `collapsed_value = max(values across all returned series at timestamp)`
- Missing timestamps are zero-filled:
  - `collapsed_value = 0.0` when no value present for expected bucket
- Used in: `monitor/metrics_service.py`

21. Trend chart normalization for plotting height
- Formula:
  - `span = hi - lo`
  - `level = round(((value - lo) / span) * chart_height)` if `span > 0`
  - else all levels set to `chart_height`
- Used in: `monitor/Opensearch/views/trends.py`

22. Trend average
- Formula: `average = sum(series.values) / len(series.values)`
- Used in: `monitor/Opensearch/views/trends.py`

### C) Log and RCA Time Window Metrics

23. Timeframe to minutes
- Formula:
  - `Xm -> X`
  - `Xh -> X * 60`
  - `Xd -> X * 1440`
- Used in: `monitor/utils.py`, consumed by log/trend flows

24. Log search time window
- Formula in query: `@timestamp in [now-minutes, now]`
- Used in: `monitor/client.py::search_logs`

25. RCA analysis window around spike timestamp
- Formula:
  - `start = spike_ts - window_min`
  - `end = spike_ts + window_min`
- Used in: `monitor/Opensearch/views/root_cause.py`

26. Data stream age in minutes
- Formula:
  - `delta = now_utc - last_seen_utc`
  - `total_minutes = int(delta.total_seconds() / 60)`
- Used in: `monitor/Opensearch/views/data_streams.py`

### D) Status and Alert Classification Formulas

27. Generic threshold classifier (symbol/color)
- Formula:
  - Critical if `value >= crit_threshold`
  - Warning if `warn_threshold <= value < crit_threshold`
  - Healthy otherwise
- Used in: `monitor/utils.py`, consumed across views

28. Global thresholds (from config)
- CPU: `warn=70`, `crit=90`
- Heap: `warn=75`, `crit=90`
- Disk: `warn=80`, `crit=90`
- Used in: Quick Summary, Node Performance, Trends readout

29. Data stream staleness severity
- Formula:
  - Red if `age_minutes >= 240`
  - Yellow if `age_minutes >= 60`
  - Green otherwise
- Used in: `monitor/Opensearch/views/data_streams.py`

30. Trend narrative: heap spike detection
- Formula condition: `peak_heap >= latest_heap * 1.4` (with `latest_heap > 0`)
- Used in: `monitor/Opensearch/views/trends.py`

31. Trend narrative: indexing burst detection
- Formula condition: `peak_indexing >= max(latest_indexing * 1.5, 1.0)`
- Used in: `monitor/Opensearch/views/trends.py`

32. Trend narrative: CPU severity
- Formula conditions:
  - Critical if `peak_cpu >= CPU_CRIT`
  - Warning if `peak_cpu >= CPU_WARN`
- Used in: `monitor/Opensearch/views/trends.py`

33. Shard state counts
- Formula examples:
  - `active_count = count(state == STARTED)`
  - `unassigned_count = count(state == UNASSIGNED)`
  - `relocating_count = count(state == RELOCATING)`
  - `initializing_count = count(state == INITIALIZING)`
- Used in:
  - `monitor/Opensearch/views/quick_summary.py`
  - `monitor/Opensearch/views/shard_overview.py`

## 5) Metrics That Are Displayed But Not Calculated Locally

These are read directly from OpenSearch and displayed as-is (no arithmetic in monitor):
- Cluster status (`green/yellow/red`)
- Node CPU percent in cluster stats/node stats payloads
- Cluster docs/indexing/search totals from `/_cluster/stats`
- Index doc counts, shard counts, replica counts from cat APIs
- Cluster health shard counters and pending tasks

## 6) Suggested Mentor Walkthrough Script (10-15 min)

1. Start with architecture
- Show `monitor/cli.py` -> `monitor/menus.py` -> one view (for example `quick_summary.py`).

2. Explain separation of concerns
- Views render.
- `client.py` fetches.
- `metrics_service.py` routes and normalizes trends.
- `utils.py` centralizes thresholds/formatting behavior.

3. Deep dive into formulas
- Open `quick_summary.py` and `node_performance.py` for `%` calculations.
- Open `poller_history.py` and `metrics_service.py` for indexing-rate and trend math.
- Open `trends.py` for chart normalization and heuristic readouts.
- Open `data_streams.py` for staleness age computation.

4. End with reliability behavior
- Mention defensive denominator checks (`if total > 0 else 0`).
- Mention source fallback (`poller -> Prometheus`) and missing-sample zero-fill.
- Mention threshold-based health interpretation consistency via `status_symbol/status_color`.

## 7) Quick File Map For Demo

- Entry and menus: `monitor/cli.py`, `monitor/menus.py`
- APIs: `monitor/client.py`
- Metric routing and trend backend: `monitor/metrics_service.py`
- Poller history aggregation: `monitor/poller_history.py`
- OpenSearch views: `monitor/Opensearch/views/*.py`
- Shared helpers and thresholds: `monitor/utils.py`, `monitor/config.py`
