# Poller Metrics Explanation

This document explains all metrics collected by the poller in `poller/` and why each is important for OpenSearch health monitoring.

## 1) Poller Scope

The poller is focused on **OpenSearch process health**, not full host-level observability.

Data is collected from two sources:
- OpenSearch API (`/_nodes/stats`) for node-level process/JVM/index/threadpool stats
- Linux `/proc/<pid>` for OpenSearch process file-descriptor and process I/O counters

Each poll cycle writes one JSON record to:
- `poller/data/metrics_YYYY-MM-DD.jsonl`

## 2) Output Record Structure

Each record has this top-level shape:

```json
{
  "ts": 1774539708,
  "timestamp": "2026-03-26T21:11:48.587716+05:30",
  "nodes": {
    "node-1": {
      "...node metrics...": "..."
    }
  },
  "host": {
    "...process metrics...": "..."
  }
}
```

## 3) Node Metrics (from OpenSearch API)

These are per-node metrics under `nodes.<node_name>`.

### `cpu_pct`
- Source: `process.cpu.percent`
- Meaning: CPU usage % of the OpenSearch process for the node
- Why we poll it: Detects CPU saturation and contention impacting indexing/search latency

### `heap_used_bytes`, `heap_max_bytes`, `heap_pct`
- Source: `jvm.mem.heap_used_in_bytes`, `jvm.mem.heap_max_in_bytes`
- Formula: `heap_pct = heap_used_bytes / heap_max_bytes * 100`
- Meaning: JVM heap pressure for OpenSearch
- Why we poll it: High heap pressure increases GC activity and risk of memory-related slowdowns

### `jvm_thread_count`, `jvm_thread_peak_count`
- Source: `jvm.threads.count`, `jvm.threads.peak_count`
- Meaning: Current JVM thread count and the peak thread count observed since node start
- Why we poll it: Helps distinguish normal load from thread growth or leaks

### `disk_store_bytes`, `disk_total_bytes`, `disk_pct`
- Source:
  - `indices.store.size_in_bytes` (OpenSearch-owned data size)
  - `fs.total.total_in_bytes` (filesystem capacity)
- Formula: `disk_pct = (disk_total_bytes - fs.free_in_bytes) / disk_total_bytes * 100`
- Meaning: How much of the node filesystem is in use
- Why we poll it: Prevents disk exhaustion and shard allocation issues

### `index_total`
- Source: `indices.indexing.index_total` (cumulative counter)
- Meaning: Total index operations processed since node start
- Why we poll it: Useful baseline counter for indexing throughput trend analysis via deltas

### `thread_pool`
- Tracked pools: `write`, `search`
- Captured fields per pool:
  - `queue`: queued requests waiting for worker threads
  - `active`: currently running tasks
  - `rejected`: cumulative rejected tasks
- Why we poll it:
  - `queue` indicates backpressure building up
  - `active` indicates current load/concurrency
  - `rejected` indicates capacity breach and user-visible failures

## 4) Derived Node Rate Metrics

These metrics are computed in the poller by diffing cumulative counters between consecutive polls.

### `gc_pause_rate_ms_per_s`
- Inputs: `gc_young_ms`, `gc_old_ms` cumulative GC pause time (milliseconds)
- Formula:
  - `young_delta = max(0, curr_young - prev_young)`
  - `old_delta = max(0, curr_old - prev_old)`
  - `gc_pause_rate_ms_per_s = (young_delta + old_delta) / elapsed_seconds`
- Unit: milliseconds of GC pause per second of wall time
- Why we poll it: Converts cumulative GC counters into an immediate pressure signal

### `tp_write_rejected_per_s`, `tp_search_rejected_per_s`
- Input: per-pool cumulative `rejected` counters
- Formula: `max(0, curr_rejected - prev_rejected) / elapsed_seconds`
- Unit: rejected tasks per second
- Why we poll it: Captures live threadpool overload rate instead of just lifetime totals

## 5) Host Section Metrics (OpenSearch Process on Linux)

These are under `host` and are tied to the OpenSearch process PID.

### `pid`
- Meaning: Process ID identified using `OS_PROCESS_KEYWORD`
- Why we poll it: Confirms which process was sampled and helps troubleshooting restarts

### `fd_count`, `fd_limit`, `fd_pct`
- Source:
  - `/proc/<pid>/fd` for open descriptor count
  - process/file limits for max open files
- Formula: `fd_pct = fd_count / fd_limit * 100`
- Meaning: File descriptor pressure on OpenSearch process
- Why we poll it: FD exhaustion can cause connection, segment, and file-handle failures

### `io_read_bytes`, `io_write_bytes`
- Source: `/proc/<pid>/io` cumulative process I/O counters
- Meaning: Total bytes read/written by OpenSearch process since start
- Why we poll it: Serves as base counters to derive storage throughput behavior

### `io_read_bps`, `io_write_bps`
- Formula: `max(0, curr_bytes - prev_bytes) / elapsed_seconds`
- Unit: bytes per second
- Meaning: Process-level storage read/write rates
- Why we poll it: Indicates ongoing I/O pressure and workload pattern shifts

### `fd_note`
- Present when permissions prevent reading `/proc/<pid>` details
- Meaning: Poller found process PID but could not read FD/I/O metrics
- Why we poll it: Makes missing metrics explicit and actionable

## 6) Counter-Reset and Safety Handling

The poller clamps negative deltas to `0` using safe-delta logic. This handles:
- OpenSearch node restarts
- PID changes
- Counter resets

Without this guard, derived rates can become negative and misleading.

## 7) Why These Metrics Were Chosen

This metric set is intentionally small but high-signal for OpenSearch operations:
- Capacity: `disk_pct`, `fd_pct`
- Performance pressure: `cpu_pct`, `heap_pct`, `gc_pause_rate_ms_per_s`
- Throughput/backpressure: `index_total`, threadpool queues, rejection rates
- Storage stress: `io_read_bps`, `io_write_bps`

Together, they let us quickly answer:
- Is the node overloaded right now?
- Is memory/GC causing latency?
- Is indexing/search under backpressure?
- Are we approaching resource limits that can cause outages?

## 8) Presentation Notes (Quick Talk Track)

Use this short flow in the meeting:
1. Start with **CPU + Heap + GC rate** to show compute and memory pressure.
2. Move to **JVM thread count + Threadpool queue/rejections** to show user-facing overload risk.
3. Show **Disk + FD usage** to cover hard capacity limits.
4. End with **I/O rates + index_total trend** to explain workload behavior over time.
