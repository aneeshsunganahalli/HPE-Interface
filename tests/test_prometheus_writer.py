"""
Unit tests for poller/storage/prometheus_writer.py

Tests cover:
  - _ts_ms()             — millisecond conversion
  - _add()               — value filtering (None, NaN, inf, valid)
  - _build_series()      — full record → series list
  - write_record()       — disabled-flag short-circuit + exception swallowing
  - _get_writer()        — singleton behaviour

Run with:
    source venv/bin/activate
    python -m pytest tests/test_prometheus_writer.py -v
"""

from __future__ import annotations

import math
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Module under test ──────────────────────────────────────────────────────────
from poller.storage.prometheus_writer import (
    _add,
    _build_series,
    _ts_ms,
    write_record,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def minimal_record():
    """Minimal valid poll record — one node, no host metrics."""
    return {
        "ts": 1_780_500_000,
        "timestamp": "2026-07-01T12:00:00+00:00",
        "nodes": {
            "node-1": {
                "cpu_pct": 10.0,
                "heap_pct": 50.0,
                "heap_used_bytes": 268_435_456,
                "heap_max_bytes": 536_870_912,
                "jvm_thread_count": 123,
                "jvm_thread_peak_count": 130,
                "disk_store_bytes": 1_000_000,
                "disk_total_bytes": 500_000_000_000,
                "disk_pct": 0.2,
                "index_total": 100_000,
                "gc_pause_rate_ms_per_s": 2.5,
                "thread_pool": {
                    "write":  {"queue": 0, "active": 1, "rejected": 0},
                    "search": {"queue": 2, "active": 3, "rejected": 0},
                },
                "tp_write_rejected_per_s":  0.0,
                "tp_search_rejected_per_s": 0.0,
            }
        },
        "host": {},
    }


@pytest.fixture()
def full_record(minimal_record):
    """Full record including host metrics."""
    minimal_record["host"] = {
        "fd_count": 839,
        "fd_limit": 524_288,
        "fd_pct": 0.16,
        "io_read_bps": 1024.0,
        "io_write_bps": 2048.0,
    }
    return minimal_record


@pytest.fixture()
def multi_node_record():
    """Two-node record for label isolation tests."""
    def _node(cpu, heap_pct):
        return {
            "cpu_pct": cpu,
            "heap_pct": heap_pct,
            "heap_used_bytes": 100_000_000,
            "heap_max_bytes": 536_870_912,
            "jvm_thread_count": 120,
            "jvm_thread_peak_count": 128,
            "disk_store_bytes": 500_000,
            "disk_total_bytes": 1_000_000_000_000,
            "disk_pct": 0.05,
            "index_total": 50_000,
            "gc_pause_rate_ms_per_s": 0.0,
            "thread_pool": {
                "write":  {"queue": 0, "active": 0, "rejected": 0},
                "search": {"queue": 0, "active": 0, "rejected": 0},
            },
            "tp_write_rejected_per_s":  0.0,
            "tp_search_rejected_per_s": 0.0,
        }

    return {
        "ts": 1_780_500_000,
        "timestamp": "2026-07-01T12:00:00+00:00",
        "nodes": {
            "node-1": _node(20.0, 40.0),
            "node-2": _node(35.0, 70.0),
        },
        "host": {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# _ts_ms
# ─────────────────────────────────────────────────────────────────────────────

class TestTsMs:
    def test_converts_epoch_seconds_to_milliseconds(self):
        assert _ts_ms(1_780_500_000) == 1_780_500_000_000

    def test_zero(self):
        assert _ts_ms(0) == 0

    def test_large_timestamp(self):
        epoch = int(time.time())
        assert _ts_ms(epoch) == epoch * 1000


# ─────────────────────────────────────────────────────────────────────────────
# _add
# ─────────────────────────────────────────────────────────────────────────────

class TestAdd:
    def _call(self, value):
        series = []
        _add(series, 1_000_000, {"job": "test"}, "test_metric", value)
        return series

    def test_valid_float(self):
        series = self._call(42.5)
        assert len(series) == 1
        assert series[0]["values"] == [42.5]
        assert series[0]["metric"]["__name__"] == "test_metric"

    def test_valid_int_cast_to_float(self):
        series = self._call(100)
        assert series[0]["values"] == [100.0]

    def test_valid_zero(self):
        series = self._call(0)
        assert len(series) == 1
        assert series[0]["values"] == [0.0]

    def test_none_skipped(self):
        assert self._call(None) == []

    def test_nan_skipped(self):
        assert self._call(float("nan")) == []

    def test_positive_inf_skipped(self):
        assert self._call(float("inf")) == []

    def test_negative_inf_skipped(self):
        assert self._call(float("-inf")) == []

    def test_non_numeric_string_skipped(self):
        assert self._call("not-a-number") == []

    def test_timestamp_stored(self):
        series = []
        _add(series, 9_999_999_999, {"job": "j"}, "m", 1.0)
        assert series[0]["timestamps"] == [9_999_999_999]

    def test_labels_stored(self):
        series = []
        labels = {"job": "hpe", "node": "n1"}
        _add(series, 0, labels, "cpu", 55.0)
        assert series[0]["metric"]["job"] == "hpe"
        assert series[0]["metric"]["node"] == "n1"
        assert series[0]["metric"]["__name__"] == "cpu"


# ─────────────────────────────────────────────────────────────────────────────
# _build_series
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildSeries:

    def _metric_names(self, series):
        return [s["metric"]["__name__"] for s in series]

    def _get(self, series, name, **label_filter):
        for s in series:
            if s["metric"]["__name__"] != name:
                continue
            if all(s["metric"].get(k) == v for k, v in label_filter.items()):
                return s
        return None

    # ── Series count ──────────────────────────────────────────────────────────

    def test_node_only_produces_15_series(self, minimal_record):
        # 11 per-node + 6 thread-pool (2 pools × 3) = 17
        series = _build_series(minimal_record)
        assert len(series) == 17

    def test_full_record_produces_20_series(self, full_record):
        # 17 node + 5 host = 22
        series = _build_series(full_record)
        assert len(series) == 22

    def test_two_nodes_produces_30_series(self, multi_node_record):
        # (11 + 6) × 2 nodes = 34
        series = _build_series(multi_node_record)
        assert len(series) == 34

    def test_empty_nodes_and_host_produces_zero_series(self):
        record = {"ts": 1_000_000, "timestamp": "x", "nodes": {}, "host": {}}
        assert _build_series(record) == []

    # ── Per-node metrics ──────────────────────────────────────────────────────

    def test_cpu_value_and_label(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_cpu_percent", node="node-1")
        assert s is not None
        assert s["values"] == [10.0]
        assert s["metric"]["job"] == "hpe_opensearch_poller"

    def test_heap_used_bytes(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_heap_used_bytes", node="node-1")
        assert s["values"] == [268_435_456.0]

    def test_gc_pause_rate(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_gc_pause_rate_ms_per_s", node="node-1")
        assert s["values"] == [2.5]

    def test_jvm_thread_count(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_jvm_thread_count", node="node-1")
        assert s["values"] == [123.0]

    def test_jvm_thread_peak_count(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_jvm_thread_peak_count", node="node-1")
        assert s["values"] == [130.0]

    def test_index_total(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_index_total", node="node-1")
        assert s["values"] == [100_000.0]

    # ── Thread pool metrics ───────────────────────────────────────────────────

    def test_threadpool_queue_write(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_threadpool_queue", node="node-1", pool="write")
        assert s is not None
        assert s["values"] == [0.0]

    def test_threadpool_queue_search(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_threadpool_queue", node="node-1", pool="search")
        assert s["values"] == [2.0]

    def test_threadpool_active_has_pool_label(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_threadpool_active", node="node-1", pool="search")
        assert s["values"] == [3.0]

    def test_rejected_rate_label(self, minimal_record):
        series = _build_series(minimal_record)
        s = self._get(series, "opensearch_node_threadpool_rejected_per_s",
                      node="node-1", pool="write")
        assert s["values"] == [0.0]

    # ── Host metrics ──────────────────────────────────────────────────────────

    def test_host_fd_count(self, full_record):
        series = _build_series(full_record)
        s = self._get(series, "opensearch_host_fd_count")
        assert s["values"] == [839.0]

    def test_host_io_read_bps(self, full_record):
        series = _build_series(full_record)
        s = self._get(series, "opensearch_host_io_read_bps")
        assert s["values"] == [1024.0]

    def test_host_metrics_skipped_on_permission_error(self):
        record = {
            "ts": 1_000_000,
            "timestamp": "x",
            "nodes": {},
            "host": {"permission_error": True, "fd_count": 999},
        }
        names = [s["metric"]["__name__"] for s in _build_series(record)]
        assert not any("host" in n for n in names)

    # ── Label correctness across nodes ────────────────────────────────────────

    def test_node_labels_isolated(self, multi_node_record):
        series = _build_series(multi_node_record)
        n1 = self._get(series, "opensearch_node_cpu_percent", node="node-1")
        n2 = self._get(series, "opensearch_node_cpu_percent", node="node-2")
        assert n1["values"] == [20.0]
        assert n2["values"] == [35.0]

    # ── Timestamp propagation ─────────────────────────────────────────────────

    def test_all_series_share_same_timestamp(self, full_record):
        expected_ms = full_record["ts"] * 1000
        series = _build_series(full_record)
        for s in series:
            assert s["timestamps"] == [expected_ms], (
                f"Wrong timestamp on {s['metric']['__name__']}"
            )

    # ── Missing / None values silently skipped ────────────────────────────────

    def test_missing_cpu_pct_skipped(self):
        record = {
            "ts": 1_000_000,
            "timestamp": "x",
            "nodes": {
                "node-1": {
                    # cpu_pct intentionally absent
                    "heap_pct": 55.0,
                    "heap_used_bytes": 100_000_000,
                    "heap_max_bytes": 536_870_912,
                    "disk_store_bytes": None,   # explicitly None
                    "disk_total_bytes": 1_000_000_000,
                    "disk_pct": 0.0,
                    "index_total": 0,
                    "gc_pause_rate_ms_per_s": 0.0,
                    "thread_pool": {},
                }
            },
            "host": {},
        }
        names = [s["metric"]["__name__"] for s in _build_series(record)]
        assert "opensearch_node_cpu_percent" not in names
        assert "opensearch_node_disk_store_bytes" not in names
        assert "opensearch_node_heap_percent" in names

    # ── Job label ─────────────────────────────────────────────────────────────

    def test_job_label_present_on_all_series(self, full_record):
        series = _build_series(full_record)
        for s in series:
            assert s["metric"].get("job") == "hpe_opensearch_poller", (
                f"Missing job label on {s['metric']['__name__']}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# write_record (integration-level, with mocked RemoteWriter)
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteRecord:

    def test_disabled_flag_skips_everything(self, full_record):
        """When PROMETHEUS_REMOTE_WRITE_ENABLED is False, no network call is made."""
        with patch("poller.storage.prometheus_writer.PROMETHEUS_REMOTE_WRITE_ENABLED", False):
            with patch("poller.storage.prometheus_writer._get_writer") as mock_get:
                write_record(full_record)
                mock_get.assert_not_called()

    def test_sends_series_when_enabled(self, full_record):
        mock_writer = MagicMock()
        with patch("poller.storage.prometheus_writer.PROMETHEUS_REMOTE_WRITE_ENABLED", True):
            with patch("poller.storage.prometheus_writer._get_writer", return_value=mock_writer):
                write_record(full_record)
                mock_writer.send.assert_called_once()
                sent_series = mock_writer.send.call_args[0][0]
                assert len(sent_series) == 20

    def test_exception_does_not_propagate(self, full_record):
        """A network failure must never crash the caller."""
        mock_writer = MagicMock()
        mock_writer.send.side_effect = ConnectionError("Prometheus is down")
        with patch("poller.storage.prometheus_writer.PROMETHEUS_REMOTE_WRITE_ENABLED", True):
            with patch("poller.storage.prometheus_writer._get_writer", return_value=mock_writer):
                # Should NOT raise
                write_record(full_record)

    def test_empty_series_not_sent(self):
        """If _build_series returns empty list, send() is not called."""
        empty_record = {"ts": 1_000_000, "timestamp": "x", "nodes": {}, "host": {}}
        mock_writer = MagicMock()
        with patch("poller.storage.prometheus_writer.PROMETHEUS_REMOTE_WRITE_ENABLED", True):
            with patch("poller.storage.prometheus_writer._get_writer", return_value=mock_writer):
                write_record(empty_record)
                mock_writer.send.assert_not_called()

    def test_correct_series_count_one_node_with_host(self, full_record):
        mock_writer = MagicMock()
        with patch("poller.storage.prometheus_writer.PROMETHEUS_REMOTE_WRITE_ENABLED", True):
            with patch("poller.storage.prometheus_writer._get_writer", return_value=mock_writer):
                write_record(full_record)
                series = mock_writer.send.call_args[0][0]
                names = [s["metric"]["__name__"] for s in series]
                # Confirm every expected metric group is present
                assert any("cpu" in n for n in names)
                assert any("heap" in n for n in names)
                assert any("threadpool" in n for n in names)
                assert any("host_fd" in n for n in names)
                assert any("host_io" in n for n in names)


# ─────────────────────────────────────────────────────────────────────────────
# _get_writer singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestGetWriter:
    def test_singleton_reused(self):
        import poller.storage.prometheus_writer as pw
        pw._writer = None  # reset
        with patch("poller.storage.prometheus_writer.RemoteWriter") as MockRW:
            MockRW.return_value = MagicMock()
            w1 = pw._get_writer()
            w2 = pw._get_writer()
            assert w1 is w2
            MockRW.assert_called_once()
        pw._writer = None  # clean up
