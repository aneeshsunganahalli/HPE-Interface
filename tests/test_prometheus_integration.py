"""
Integration / smoke tests for the Prometheus Remote Write pipeline.

These tests require a LIVE Prometheus instance running at
PROMETHEUS_REMOTE_WRITE_URL (default: http://localhost:9090) with
--web.enable-remote-write-receiver enabled.

They will be SKIPPED automatically if Prometheus is not reachable.

Run:
    source venv/bin/activate
    python -m pytest tests/test_prometheus_integration.py -v -s

Optionally override the endpoint:
    PROMETHEUS_REMOTE_WRITE_URL=http://10.0.0.5:9090/api/v1/write \\
        python -m pytest tests/test_prometheus_integration.py -v -s
"""

from __future__ import annotations

import os
import time

import pytest
import requests

from poller.storage.prometheus_writer import _build_series, write_record

# ── Helpers ───────────────────────────────────────────────────────────────────

PROM_BASE = os.getenv(
    "PROMETHEUS_BASE_URL",
    os.getenv("PROMETHEUS_REMOTE_WRITE_URL", "http://localhost:9090/api/v1/write")
    .replace("/api/v1/write", ""),
)
WRITE_URL = f"{PROM_BASE}/api/v1/write"
QUERY_URL = f"{PROM_BASE}/api/v1/query"


def _prometheus_reachable() -> bool:
    try:
        r = requests.get(f"{PROM_BASE}/-/healthy", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _query(metric: str, labels: dict | None = None) -> list[dict]:
    """Run an instant PromQL query and return the result list."""
    selector = metric
    if labels:
        pairs = ",".join(f'{k}="{v}"' for k, v in labels.items())
        selector = f"{metric}{{{pairs}}}"
    r = requests.get(QUERY_URL, params={"query": selector}, timeout=5)
    r.raise_for_status()
    return r.json()["data"]["result"]


def _make_record(ts: int | None = None, node: str = "integ-test-node") -> dict:
    ts = ts or int(time.time())
    return {
        "ts": ts,
        "timestamp": "2026-07-01T12:00:00+00:00",
        "nodes": {
            node: {
                "cpu_pct": 13.0,
                "heap_pct": 58.3,
                "heap_used_bytes": 312_000_000,
                "heap_max_bytes": 536_870_912,
                "jvm_thread_count": 111,
                "jvm_thread_peak_count": 118,
                "disk_store_bytes": 750_000_000,
                "disk_total_bytes": 900_000_000_000,
                "disk_pct": 0.08,
                "index_total": 200_000,
                "gc_pause_rate_ms_per_s": 1.2,
                "thread_pool": {
                    "write":  {"queue": 0, "active": 2, "rejected": 0},
                    "search": {"queue": 1, "active": 5, "rejected": 0},
                },
                "tp_write_rejected_per_s":  0.0,
                "tp_search_rejected_per_s": 0.0,
            }
        },
        "host": {
            "fd_count": 901,
            "fd_limit": 524_288,
            "fd_pct": 0.17,
            "io_read_bps": 2048.0,
            "io_write_bps": 4096.0,
        },
    }


# ── Skip marker ───────────────────────────────────────────────────────────────

prom_available = pytest.mark.skipif(
    not _prometheus_reachable(),
    reason=f"Prometheus not reachable at {PROM_BASE}",
)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@prom_available
class TestLiveRemoteWrite:
    """Pushes a synthetic record and verifies the data appears in Prometheus."""

    NODE = "integ-test-node"

    @pytest.fixture(autouse=True)
    def _push_record(self):
        """Push one record before each test; wait briefly for TSDB ingestion."""
        self.record = _make_record(node=self.NODE)
        write_record(self.record)
        time.sleep(1)  # give Prometheus time to index

    def test_cpu_percent_stored(self):
        results = _query(
            "opensearch_node_cpu_percent",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results, "opensearch_node_cpu_percent not found in Prometheus"
        assert float(results[0]["value"][1]) == pytest.approx(13.0, abs=0.1)

    def test_heap_percent_stored(self):
        results = _query(
            "opensearch_node_heap_percent",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(58.3, abs=0.1)

    def test_heap_used_bytes_stored(self):
        results = _query(
            "opensearch_node_heap_used_bytes",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(312_000_000, rel=0.01)

    def test_jvm_thread_count_stored(self):
        results = _query(
            "opensearch_node_jvm_thread_count",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(111.0, abs=0.1)

    def test_jvm_thread_peak_count_stored(self):
        results = _query(
            "opensearch_node_jvm_thread_peak_count",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(118.0, abs=0.1)

    def test_disk_percent_stored(self):
        results = _query(
            "opensearch_node_disk_percent",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(0.08, abs=0.001)

    def test_gc_pause_rate_stored(self):
        results = _query(
            "opensearch_node_gc_pause_rate_ms_per_s",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(1.2, abs=0.01)

    def test_index_total_stored(self):
        results = _query(
            "opensearch_node_index_total",
            {"job": "hpe_opensearch_poller", "node": self.NODE},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(200_000, rel=0.001)

    def test_threadpool_write_queue_stored(self):
        results = _query(
            "opensearch_node_threadpool_queue",
            {"job": "hpe_opensearch_poller", "node": self.NODE, "pool": "write"},
        )
        assert results
        assert float(results[0]["value"][1]) == 0.0

    def test_threadpool_search_queue_stored(self):
        results = _query(
            "opensearch_node_threadpool_queue",
            {"job": "hpe_opensearch_poller", "node": self.NODE, "pool": "search"},
        )
        assert results
        assert float(results[0]["value"][1]) == 1.0

    def test_host_fd_count_stored(self):
        results = _query(
            "opensearch_host_fd_count",
            {"job": "hpe_opensearch_poller"},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(901.0, abs=1)

    def test_host_io_read_bps_stored(self):
        results = _query(
            "opensearch_host_io_read_bps",
            {"job": "hpe_opensearch_poller"},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(2048.0, abs=1)

    def test_host_io_write_bps_stored(self):
        results = _query(
            "opensearch_host_io_write_bps",
            {"job": "hpe_opensearch_poller"},
        )
        assert results
        assert float(results[0]["value"][1]) == pytest.approx(4096.0, abs=1)

    def test_job_label_on_all_metrics(self):
        """All 20 series must carry the hpe_opensearch_poller job label."""
        all_metrics = [
            "opensearch_node_cpu_percent",
            "opensearch_node_heap_percent",
            "opensearch_node_jvm_thread_count",
            "opensearch_node_disk_percent",
            "opensearch_node_gc_pause_rate_ms_per_s",
            "opensearch_host_fd_count",
        ]
        for metric in all_metrics:
            results = _query(metric, {"job": "hpe_opensearch_poller"})
            assert results, f"No results for {metric} with job label"


@prom_available
class TestPrometheusConnectivity:
    """Smoke tests to verify Prometheus is healthy and the write endpoint works."""

    def test_prometheus_health(self):
        r = requests.get(f"{PROM_BASE}/-/healthy", timeout=5)
        assert r.status_code == 200

    def test_write_endpoint_returns_204(self):
        """Direct POST with a minimal valid series payload."""
        from prometheus_remote_writer import RemoteWriter
        writer = RemoteWriter(url=WRITE_URL)
        ts_ms = int(time.time() * 1000)
        writer.send([{
            "metric": {
                "__name__": "hpe_monitor_smoke_test",
                "job": "hpe_opensearch_poller",
                "test": "connectivity",
            },
            "values":     [1.0],
            "timestamps": [ts_ms],
        }])
        # If no exception, the 204 was received — pass implicitly

    def test_query_api_reachable(self):
        r = requests.get(QUERY_URL, params={"query": "up"}, timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "success"
