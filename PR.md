# feat: Add continuous OpenSearch metrics poller

## Summary

Introduces a modular, continuously-running poller (`python -m poller`) that collects OpenSearch-specific metrics at a configurable interval and appends them to daily-rotating JSONL files. This lays the foundation for trend visualization in the CLI without depending on Prometheus.

---

## Motivation

The existing `monitor/` CLI provides point-in-time snapshots only. To detect slow degradation (heap creep, growing GC pressure, FD exhaustion) we need continuous polling and persistent storage of trends. Prometheus covers some of this, but several high-signal metrics — FD count versus ulimit, process-level I/O, GC pause rate — are not available from any existing backend.

---

## Changes

### New: `poller/` module

```
poller/
  __main__.py              ← entry point: python -m poller
  config.py                ← interval, output dir, connection settings (reads .env)
  poller.py                ← orchestrator loop
  collectors/
    opensearch_api.py      ← 5 metrics via /_nodes/stats API
    system.py              ← FD count + process I/O via /proc/<pid>
  storage/
    writer.py              ← daily-rotating JSONL writer
```

### Modified
- `requirements.txt` — added `psutil>=5.9.0`
- `.gitignore` — excluded `poller/data/` (generated JSONL files)
- `README.md` — added poller usage commands

---

## Metrics collected (per poll cycle)

All metrics are **scoped to the OpenSearch process**, not the host OS.

| Metric | Source | Notes |
|--------|--------|-------|
| CPU % | `process.cpu.percent` | OS process only, not system-wide |
| JVM Heap % | `jvm.mem.heap_used_percent` | The memory metric that matters for OpenSearch |
| Disk % | `indices.store.size_in_bytes / fs.total.total_in_bytes` | Data OpenSearch owns vs capacity |
| GC Pause Rate | Delta of `jvm.gc.collectors.*.collection_time_in_millis` / elapsed s | ms of GC per second of wall time |
| Thread Pool | `thread_pool.{write,search}.{queue,rejected,active}` | Queue depth + per-second rejection rate |
| FD Count vs Limit | `/proc/<pid>/fd` count + `RLIMIT_NOFILE` | Requires same OS user or sudo |
| Process I/O Rate | `/proc/<pid>/io` delta → bytes/s | Requires same OS user or sudo |

---

## Output format

One JSON line per poll cycle, appended to `poller/data/metrics_YYYY-MM-DD.jsonl`:

```json
{
  "ts": 1774083237,
  "timestamp": "2026-03-21T04:53:57-04:00",
  "nodes": {
    "node-1": {
      "cpu_pct": 6,
      "heap_pct": 54.78,
      "heap_used_bytes": 294096328,
      "heap_max_bytes": 536870912,
      "disk_store_bytes": 413422,
      "disk_total_bytes": 914758643712,
      "disk_pct": 0.0,
      "gc_pause_rate_ms_per_s": 0.0,
      "thread_pool": {
        "write": { "queue": 0, "rejected": 0, "active": 0 },
        "search": { "queue": 0, "rejected": 0, "active": 0 }
      },
      "tp_write_rejected_per_s": 0.0,
      "tp_search_rejected_per_s": 0.0
    }
  },
  "host": {
    "pid": 5104,
    "fd_count": 839,
    "fd_limit": 524288,
    "fd_pct": 0.16,
    "io_read_bytes": 221237248,
    "io_write_bytes": 56320000,
    "io_read_bps": 0.0,
    "io_write_bps": 0.0
  }
}
```

---

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Default: 15s interval, writes to poller/data/
python -m poller

# Faster polling with live stdout output
python -m poller --interval 5 --verbose

# Full metrics including FD + I/O (needs venv Python under sudo)
sudo venv/bin/python -m poller --interval 15

# Custom output location
python -m poller --interval 30 --output-dir /var/log/hpe-monitor/poller
```

> **Note on FD / I/O metrics:** These require the poller to run as the same OS user that owns the OpenSearch process. When run as a different user, the `host` block includes a `fd_note` field explaining this instead of emitting null values.

---

## Testing

```bash
# Verify records are written and all metric keys are present
python -m poller --interval 10 --output-dir /tmp/test_poll &
sleep 25 && kill %1
python3 -c "
import json, glob
f = sorted(glob.glob('/tmp/test_poll/*.jsonl'))[-1]
lines = [l for l in open(f) if l.strip()]
print(f'Records: {len(lines)}')
r = json.loads(lines[-1])
print('Nodes:', list(r['nodes'].keys()))
print('Host keys:', list(r['host'].keys()))
"
```

---

## What's next

- [ ] CLI view in `monitor/` that reads from the JSONL store for offline trend visualization
- [ ] Extend poller to cover Kafka and Logstash services
- [ ] Alert checkpointing: log threshold crossings to a separate events file
