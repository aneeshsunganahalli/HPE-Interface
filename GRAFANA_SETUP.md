# Grafana Dashboard Setup — HPE OpenSearch Poller

> **Status:** Active  
> **Requires:** Prometheus ≥ 2.52 running with `--web.enable-remote-write-receiver` · Grafana ≥ 10.0  
> **Date:** 2026-07-01

---

## Prerequisites Checklist

- [ ] Prometheus is running: `curl http://localhost:9090/-/healthy` → `Prometheus Server is Healthy`
- [ ] Remote write receiver is enabled: Prometheus was started with `--web.enable-remote-write-receiver`
- [ ] At least one poller cycle has run: `python -m poller --interval 15`
- [ ] Grafana is accessible at `http://localhost:3000`

---

## Step 1 — Add Prometheus as a Data Source

1. Open Grafana → **Connections → Data sources → Add new data source**
2. Select **Prometheus**
3. Fill in the fields:

   | Field | Value |
   |---|---|
   | Name | `Prometheus` (or `HPE-Prometheus`) |
   | URL | `http://localhost:9090` |
   | Scrape interval | `15s` (match your poller `--interval`) |
   | HTTP Method | `POST` |

4. Click **Save & test** → expect _"Successfully queried the Prometheus API"_

---

## Step 2 — Import the Dashboard (Fastest Path)

1. Grafana → **Dashboards → Import**
2. Click **Upload JSON file** — OR — paste the JSON below directly into the text area
3. Set the datasource dropdown to your Prometheus instance
4. Click **Import**

### Dashboard JSON

```json
{
  "__inputs": [
    {
      "name": "DS_PROMETHEUS",
      "label": "Prometheus",
      "description": "",
      "type": "datasource",
      "pluginId": "prometheus",
      "pluginName": "Prometheus"
    }
  ],
  "__requires": [
    { "type": "grafana",    "id": "grafana",    "name": "Grafana",    "version": "10.0.0" },
    { "type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"  },
    { "type": "panel",      "id": "timeseries", "name": "Time series","version": ""        },
    { "type": "panel",      "id": "stat",       "name": "Stat",       "version": ""        },
    { "type": "panel",      "id": "gauge",      "name": "Gauge",      "version": ""        }
  ],
  "annotations": { "list": [] },
  "description": "HPE OpenSearch poller metrics — CPU, Heap, Disk, GC, Thread Pools, FD, I/O",
  "editable": true,
  "graphTooltip": 1,
  "panels": [
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 },
      "id": 100,
      "title": "ROW 1 — Cluster Health",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": { "lineWidth": 2, "fillOpacity": 10 },
          "unit": "percent", "min": 0, "max": 100,
          "thresholds": { "mode": "absolute", "steps": [
            { "color": "green",  "value": null },
            { "color": "yellow", "value": 70   },
            { "color": "red",    "value": 85   }
          ]}
        }
      },
      "gridPos": { "h": 8, "w": 8, "x": 0, "y": 1 },
      "id": 1,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_cpu_percent{job=\"hpe_opensearch_poller\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "CPU % per Node",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": { "lineWidth": 2, "fillOpacity": 10 },
          "unit": "percent", "min": 0, "max": 100,
          "thresholds": { "mode": "absolute", "steps": [
            { "color": "green",  "value": null },
            { "color": "yellow", "value": 75   },
            { "color": "red",    "value": 90   }
          ]}
        }
      },
      "gridPos": { "h": 8, "w": 8, "x": 8, "y": 1 },
      "id": 2,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_heap_percent{job=\"hpe_opensearch_poller\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "JVM Heap % per Node",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "unit": "percent", "min": 0, "max": 100
        }
      },
      "gridPos": { "h": 8, "w": 8, "x": 16, "y": 1 },
      "id": 3,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_disk_percent{job=\"hpe_opensearch_poller\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "Disk % Used per Node",
      "type": "timeseries"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 9 },
      "id": 101,
      "title": "ROW 2 — Throughput & GC",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "unit": "ops", "custom": { "lineWidth": 2, "fillOpacity": 5 }
        }
      },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 10 },
      "id": 4,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "rate(opensearch_node_index_total{job=\"hpe_opensearch_poller\", node=~\"$node\"}[$__rate_interval])",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "Indexing Rate (ops/s)",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "unit": "ms", "custom": { "lineWidth": 2, "fillOpacity": 5 },
          "thresholds": { "mode": "absolute", "steps": [
            { "color": "green",  "value": null },
            { "color": "yellow", "value": 50   },
            { "color": "red",    "value": 100  }
          ]}
        }
      },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 10 },
      "id": 5,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_gc_pause_rate_ms_per_s{job=\"hpe_opensearch_poller\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "GC Pause Rate (ms/s) — alert > 100",
      "type": "timeseries"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 18 },
      "id": 102,
      "title": "ROW 3 — Thread Pools",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "unit": "short" } },
      "gridPos": { "h": 7, "w": 8, "x": 0, "y": 19 },
      "id": 6,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_threadpool_queue{job=\"hpe_opensearch_poller\", pool=\"write\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "Write Pool Queue Depth",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "unit": "short" } },
      "gridPos": { "h": 7, "w": 8, "x": 8, "y": 19 },
      "id": 7,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_threadpool_queue{job=\"hpe_opensearch_poller\", pool=\"search\", node=~\"$node\"}",
        "legendFormat": "{{node}}", "refId": "A"
      }],
      "title": "Search Pool Queue Depth",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "unit": "ops" } },
      "gridPos": { "h": 7, "w": 8, "x": 16, "y": 19 },
      "id": 8,
      "targets": [{
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "expr": "opensearch_node_threadpool_rejected_per_s{job=\"hpe_opensearch_poller\", node=~\"$node\"}",
        "legendFormat": "{{node}} / {{pool}}", "refId": "A"
      }],
      "title": "Thread Pool Rejection Rate (ops/s)",
      "type": "timeseries"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 26 },
      "id": 103,
      "title": "ROW 4 — Host Process",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "thresholds": { "mode": "absolute", "steps": [
            { "color": "green",  "value": null   },
            { "color": "yellow", "value": 400000 },
            { "color": "red",    "value": 470000 }
          ]}
        }
      },
      "gridPos": { "h": 7, "w": 12, "x": 0, "y": 27 },
      "id": 9,
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
          "expr": "opensearch_host_fd_count{job=\"hpe_opensearch_poller\"}",
          "legendFormat": "FD Used", "refId": "A"
        },
        {
          "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
          "expr": "opensearch_host_fd_limit{job=\"hpe_opensearch_poller\"}",
          "legendFormat": "FD Limit", "refId": "B"
        }
      ],
      "title": "File Descriptors: Count vs Limit",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "unit": "Bps" } },
      "gridPos": { "h": 7, "w": 12, "x": 12, "y": 27 },
      "id": 10,
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
          "expr": "opensearch_host_io_read_bps{job=\"hpe_opensearch_poller\"}",
          "legendFormat": "Read", "refId": "A"
        },
        {
          "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
          "expr": "opensearch_host_io_write_bps{job=\"hpe_opensearch_poller\"}",
          "legendFormat": "Write", "refId": "B"
        }
      ],
      "title": "Process I/O (bytes/s)",
      "type": "timeseries"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 38,
  "tags": ["opensearch", "hpe", "poller"],
  "templating": {
    "list": [
      {
        "current": {},
        "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
        "definition": "label_values(opensearch_node_cpu_percent{job=\"hpe_opensearch_poller\"}, node)",
        "hide": 0,
        "includeAll": true,
        "label": "Node",
        "multi": true,
        "name": "node",
        "options": [],
        "query": {
          "query": "label_values(opensearch_node_cpu_percent{job=\"hpe_opensearch_poller\"}, node)",
          "refId": "StandardVariableQuery"
        },
        "refresh": 2,
        "sort": 1,
        "type": "query"
      }
    ]
  },
  "time": { "from": "now-1h", "to": "now" },
  "timezone": "browser",
  "title": "HPE OpenSearch Poller",
  "uid": "hpe-opensearch-poller",
  "version": 1
}
```

---

## Step 3 — Manual Panel PromQL Reference

Use these queries if you prefer to build panels by hand.

### Row 1 — Cluster Health

#### CPU % per Node
```promql
opensearch_node_cpu_percent{job="hpe_opensearch_poller", node=~"$node"}
```
> Panel type: **Time series** · Unit: `percent` · Max: 100 · Thresholds: 70 % = yellow, 85 % = red

#### JVM Heap % per Node
```promql
opensearch_node_heap_percent{job="hpe_opensearch_poller", node=~"$node"}
```
> Derived (more accurate for alerting):
> ```promql
> opensearch_node_heap_used_bytes / opensearch_node_heap_max_bytes * 100
> ```

#### Disk % Used
```promql
opensearch_node_disk_percent{job="hpe_opensearch_poller", node=~"$node"}
```

#### Disk Store Growth Rate (bytes/hour)
```promql
deriv(opensearch_node_disk_store_bytes{job="hpe_opensearch_poller"}[30m]) * 3600
```

#### Estimated Hours to Full
```promql
(opensearch_node_disk_total_bytes - opensearch_node_disk_store_bytes)
  / clamp_min(deriv(opensearch_node_disk_store_bytes[1h]) * 3600, 1)
```

---

### Row 2 — Throughput & GC

#### Indexing Rate (ops/s per node)
```promql
rate(opensearch_node_index_total{job="hpe_opensearch_poller", node=~"$node"}[$__rate_interval])
```
> Legend: `{{node}}`

#### Cluster-Wide Indexing Rate
```promql
sum(rate(opensearch_node_index_total{job="hpe_opensearch_poller"}[1m]))
```

#### GC Pause Rate (ms/s)
```promql
opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller", node=~"$node"}
```
> Unit: `ms` · Alert threshold: > 100

---

### Row 3 — Thread Pools

#### Write Queue Depth
```promql
opensearch_node_threadpool_queue{job="hpe_opensearch_poller", pool="write", node=~"$node"}
```

#### Search Queue Depth
```promql
opensearch_node_threadpool_queue{job="hpe_opensearch_poller", pool="search", node=~"$node"}
```

#### Active Threads (both pools)
```promql
opensearch_node_threadpool_active{job="hpe_opensearch_poller", node=~"$node"}
```
> Legend: `{{node}} / {{pool}}`

#### Rejection Rate (ops/s)
```promql
opensearch_node_threadpool_rejected_per_s{job="hpe_opensearch_poller", node=~"$node"}
```

---

### Row 4 — Host Process

#### File Descriptors: Count vs Limit  *(two series on one panel)*
```promql
# Series A
opensearch_host_fd_count{job="hpe_opensearch_poller"}

# Series B
opensearch_host_fd_limit{job="hpe_opensearch_poller"}
```

#### FD Exhaustion %  *(Stat / Gauge — good alert candidate)*
```promql
opensearch_host_fd_count / opensearch_host_fd_limit * 100
```

#### Process I/O (bytes/s)  *(two series on one panel)*
```promql
# Series A — Read
opensearch_host_io_read_bps{job="hpe_opensearch_poller"}

# Series B — Write
opensearch_host_io_write_bps{job="hpe_opensearch_poller"}
```
> Unit: `bytes/s (Bps)`

---

## Step 4 — Template Variable: `$node`

**Dashboard settings → Variables → New variable**

| Field | Value |
|---|---|
| Type | Query |
| Name | `node` |
| Label | `Node` |
| Data source | Prometheus |
| Query | `label_values(opensearch_node_cpu_percent{job="hpe_opensearch_poller"}, node)` |
| Multi-value | ✅ |
| Include All | ✅ |
| Refresh | On time range change |

---

## Step 5 — Alerting (Grafana Unified Alerting)

### High CPU
| Field | Value |
|---|---|
| Query | `max(opensearch_node_cpu_percent{job="hpe_opensearch_poller"}) by (node)` |
| Condition | IS ABOVE `85` |
| For | `5m` |
| Labels | `severity=warning` |
| Summary | `High CPU on {{ $labels.node }}` |

### JVM Heap Critical
| Field | Value |
|---|---|
| Query | `max(opensearch_node_heap_used_bytes / opensearch_node_heap_max_bytes * 100) by (node)` |
| Condition | IS ABOVE `90` |
| For | `3m` |
| Labels | `severity=critical` |
| Summary | `JVM Heap critical on {{ $labels.node }} — OOM risk` |

### GC Pressure
| Field | Value |
|---|---|
| Query | `opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller"}` |
| Condition | IS ABOVE `100` |
| For | `2m` |
| Labels | `severity=warning` |

### Thread Pool Rejections
| Field | Value |
|---|---|
| Query | `opensearch_node_threadpool_rejected_per_s{job="hpe_opensearch_poller"}` |
| Condition | IS ABOVE `0` |
| For | `1m` |
| Labels | `severity=critical` |

### FD Exhaustion
| Field | Value |
|---|---|
| Query | `opensearch_host_fd_count / opensearch_host_fd_limit * 100` |
| Condition | IS ABOVE `80` |
| For | `5m` |
| Labels | `severity=warning` |

---

## Step 6 — Verify in the Prometheus Expression Browser

Before building panels, confirm data is present at `http://localhost:9090/graph`:

```promql
# All poller metrics (should list 20 series per poll cycle)
{job="hpe_opensearch_poller"}

# Per-metric spot checks
opensearch_node_cpu_percent
opensearch_node_heap_percent
opensearch_node_gc_pause_rate_ms_per_s{job="hpe_opensearch_poller"}
rate(opensearch_node_index_total[1m])
opensearch_host_fd_count / opensearch_host_fd_limit * 100
```

---

## Test Suite

The integration is covered by 53 automated tests in `tests/`:

```bash
# Unit tests — no Prometheus needed (safe for CI)
source venv/bin/activate
python -m pytest tests/test_prometheus_writer.py -v

# Full suite including live push & PromQL verification
python -m pytest tests/ -v

# Integration tests only (Prometheus must be running)
python -m pytest tests/test_prometheus_integration.py -v -s
```

| File | Tests | Coverage |
|---|---|---|
| `tests/test_prometheus_writer.py` | 38 | `_ts_ms`, `_add` filtering (None/NaN/±inf), `_build_series` counts + labels + timestamps, `write_record` disabled-flag + exception swallowing, singleton |
| `tests/test_prometheus_integration.py` | 15 | Live push → PromQL query for all 10 metric families, HTTP 204, Prometheus health |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **"No data" on all panels** | Run `python -m poller --interval 5 --verbose` and wait 10 s; check `http://localhost:9090/graph` |
| **Datasource test fails** | `curl http://localhost:9090/-/healthy` — confirm Prometheus is running |
| **`$node` variable is empty** | Poller hasn't run yet — `opensearch_node_cpu_percent` must exist before `label_values()` works |
| **Grafana "Metric not found"** | Label must be exactly `job="hpe_opensearch_poller"` — check for typos |
| **Import JSON fails** | The `DS_PROMETHEUS` input must match your actual datasource UID — edit in the JSON or re-select after import |
| **Poller writes JSONL but Prometheus gets nothing** | Check `.env` for `PROMETHEUS_REMOTE_WRITE_ENABLED=true` and `PROMETHEUS_REMOTE_WRITE_URL` |
| **`POST /api/v1/write → 404`** | Prometheus wasn't started with `--web.enable-remote-write-receiver` — restart with the flag |

---

## Related Files

| File | Purpose |
|---|---|
| `poller/storage/prometheus_writer.py` | Remote Write client — translates poll records → 20 time-series |
| `poller/config.py` | `PROMETHEUS_REMOTE_WRITE_URL / JOB / ENABLED` config |
| `poller/poller.py` | Calls `write_record()` after each poll cycle |
| `PROMETHEUS_GRAFANA_MIGRATION.md` | Full architecture design doc |
| `tests/test_prometheus_writer.py` | 38 unit tests |
| `tests/test_prometheus_integration.py` | 15 live integration tests |
