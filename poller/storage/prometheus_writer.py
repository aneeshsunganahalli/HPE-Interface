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
import math
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


# ── Internal helpers ──────────────────────────────────────────────────────────

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
    ts_ms = _ts_ms(record["ts"])
    job = PROMETHEUS_REMOTE_WRITE_JOB
    nodes = record.get("nodes", {})
    host = record.get("host", {})
    series: list[dict] = []

    base = _base_labels(job)

    # ── Per-node metrics ──────────────────────────────────────────────────────
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
        _add(series, ts_ms, node_labels, "opensearch_node_jvm_thread_count",
             snap.get("jvm_thread_count"))
        _add(series, ts_ms, node_labels, "opensearch_node_jvm_thread_peak_count",
             snap.get("jvm_thread_peak_count"))
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

        # ── Thread pool breakdown ─────────────────────────────────────────────
        for pool, pool_data in snap.get("thread_pool", {}).items():
            pool_labels = {**node_labels, "pool": pool}
            _add(series, ts_ms, pool_labels, "opensearch_node_threadpool_queue",
                 pool_data.get("queue"))
            _add(series, ts_ms, pool_labels, "opensearch_node_threadpool_active",
                 pool_data.get("active"))
            rate_key = f"tp_{pool}_rejected_per_s"
            _add(series, ts_ms, pool_labels,
                 "opensearch_node_threadpool_rejected_per_s",
                 snap.get(rate_key))

    # ── Host / process metrics ────────────────────────────────────────────────
    if host and not host.get("permission_error"):
        _add(series, ts_ms, base, "opensearch_host_fd_count", host.get("fd_count"))
        _add(series, ts_ms, base, "opensearch_host_fd_limit", host.get("fd_limit"))
        _add(series, ts_ms, base, "opensearch_host_fd_percent", host.get("fd_pct"))
        _add(series, ts_ms, base, "opensearch_host_io_read_bps", host.get("io_read_bps"))
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
    if not math.isfinite(v):
        return

    series.append({
        "metric": {"__name__": metric_name, **labels},
        "values": [v],
        "timestamps": [ts_ms],
    })
