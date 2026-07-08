from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import urllib3

from archive.extras.config import (
    PROMETHEUS_HOST, PROMETHEUS_PORT, PROMETHEUS_SCHEME, PROMETHEUS_TIMEOUT,
    PA_HOST, PA_PORT, PA_SCHEME, PA_TIMEOUT,
    POLLER_DATA_DIR, HISTORY_SOURCE, console,
)
from archive.extras.poller_history import PollerHistoryStore
from archive.extras.utils import is_realtime, timeframe_to_minutes, timeframe_to_prom_range


@dataclass
class TrendSeries:
    label: str
    values: list[float]
    timestamps: list[int]
    unit: str

    @property
    def peak(self) -> float:
        return max(self.values) if self.values else 0.0

    @property
    def latest(self) -> float:
        return self.values[-1] if self.values else 0.0


class MetricsProvider:

    def __init__(self) -> None:
        self._http = urllib3.PoolManager()
        self._prom_base = f"{PROMETHEUS_SCHEME}://{PROMETHEUS_HOST}:{PROMETHEUS_PORT}"
        self._pa_base = f"{PA_SCHEME}://{PA_HOST}:{PA_PORT}"
        self._poller = PollerHistoryStore(POLLER_DATA_DIR)
        self._source_pref = HISTORY_SOURCE
        self._warned: set[str] = set()

    def set_source(self, source: str) -> None:
        s = (source or "").strip().lower()
        self._source_pref = s if s in {"auto", "poller", "prometheus"} else "auto"

    # ── Node stats ───────────────────────────────────────────────

    def node_stats(self, timeframe: str = "1h") -> dict[str, Any]:
        from archive.extras.client import node_stats
        return node_stats()

    # ── Historical trends ────────────────────────────────────────

    def trends(self, timeframe: str) -> dict[str, TrendSeries]:
        _, series = self.trends_with_source(timeframe)
        return series

    def trends_with_source(self, timeframe: str) -> tuple[str, dict[str, TrendSeries]]:
        tf = "1h" if is_realtime(timeframe) else timeframe

        poller_fn = lambda: self._poller_series(tf)
        prom_fn = lambda: self._prometheus_series(tf)

        if self._source_pref == "poller":
            s = poller_fn()
            return ("poller" if _has_data(s) else "none"), s

        if self._source_pref == "prometheus":
            s = prom_fn()
            return ("prometheus" if _has_data(s) else "none"), s

        # Auto: prefer poller, fill gaps from prometheus
        poller = poller_fn()
        prom = prom_fn()
        merged = {}
        p_used, pr_used = False, False

        for key in ("cpu", "heap", "indexing_rate"):
            if poller[key].values:
                merged[key] = poller[key]
                p_used = True
            else:
                merged[key] = prom[key]
                if prom[key].values:
                    pr_used = True

        if p_used and pr_used:
            src = "mixed"
        elif p_used:
            src = "poller"
        elif _has_data(merged):
            src = "prometheus"
        else:
            src = "none"

        return src, merged

    # ── Performance Analyzer ─────────────────────────────────────

    def bottleneck_metrics(self, node_name: str) -> dict[str, float | None]:
        payload, raw = self._get_json(
            self._pa_base,
            "/_plugins/_performanceanalyzer/metrics",
            {"metrics": "Disk_Utilization,IO_TotWait", "agg": "avg,1m"},
            PA_TIMEOUT, "performance analyzer",
        )
        return {
            "disk_utilization": self._extract_value(payload, raw, "Disk_Utilization"),
            "io_tot_wait": self._extract_value(payload, raw, "IO_TotWait"),
        }

    # ── Internal: Prometheus ─────────────────────────────────────

    def _poller_series(self, tf: str) -> dict[str, TrendSeries]:
        mins = max(timeframe_to_minutes(tf), 5)
        data = self._poller.trends(mins)
        ts_cpu, v_cpu = data.get("cpu", ([], []))
        ts_heap, v_heap = data.get("heap", ([], []))
        ts_idx, v_idx = data.get("indexing_rate", ([], []))
        return {
            "cpu": TrendSeries("CPU", v_cpu, ts_cpu, "%"),
            "heap": TrendSeries("JVM Heap", v_heap, ts_heap, "bytes"),
            "indexing_rate": TrendSeries("Indexing Rate", v_idx, ts_idx, "ops/s"),
        }

    def _prometheus_series(self, tf: str) -> dict[str, TrendSeries]:
        return {
            "cpu": self._prom_query(
                "CPU", "max_over_time(opensearch_os_cpu_percent[5m])", tf, "%",
            ),
            "heap": self._prom_query(
                "JVM Heap", "max_over_time(opensearch_jvm_mem_heap_used_bytes[5m])", tf, "bytes",
            ),
            "indexing_rate": self._prom_query(
                "Indexing Rate", "sum(rate(opensearch_indices_indexing_index_total[5m]))", tf, "ops/s",
                fallback="sum(rate(opensearch_indices_indexing_index_count[5m]))",
            ),
        }

    def _prom_query(
        self, label: str, query: str, tf: str, unit: str,
        step: str = "5m", fallback: str | None = None,
    ) -> TrendSeries:
        payload, start, end, step_s = self._prom_range(query, tf, step)
        has_data = _prom_has_samples(payload)
        timestamps, values = _collapse_prom(payload, start, end, step_s)

        if fallback and not has_data:
            payload, start, end, step_s = self._prom_range(fallback, tf, step)
            timestamps, values = _collapse_prom(payload, start, end, step_s)

        return TrendSeries(label=label, values=values, timestamps=timestamps, unit=unit)

    def _prom_range(self, query: str, tf: str, step: str) -> tuple[dict, int, int, int]:
        mins = max(timeframe_to_minutes(tf), 5)
        now = int(time.time())
        start = now - (mins * 60)
        step_s = _step_to_seconds(step)

        payload, _ = self._get_json(
            self._prom_base, "/api/v1/query_range",
            {"query": query, "start": start, "end": now, "step": step},
            PROMETHEUS_TIMEOUT, "prometheus",
        )
        return payload, start, now, step_s

    # ── Internal: HTTP + extraction ──────────────────────────────

    def _get_json(self, base: str, path: str, params: dict, timeout: int, ctx: str) -> tuple[dict, str]:
        qs = urllib.parse.urlencode(params, doseq=True)
        url = f"{base}{path}?{qs}" if qs else f"{base}{path}"

        try:
            resp = self._http.request("GET", url, timeout=urllib3.Timeout(connect=timeout, read=timeout))
        except Exception as e:
            self._warn(ctx, f"Unable to reach {ctx}: {e}")
            return {}, ""

        raw = resp.data.decode("utf-8", errors="replace")
        if resp.status >= 400:
            self._warn(ctx, f"{ctx} returned HTTP {resp.status}.")
            return {}, raw
        if not raw.strip():
            return {}, ""

        try:
            return json.loads(raw), raw
        except json.JSONDecodeError:
            return {}, raw

    def _warn(self, ctx: str, msg: str) -> None:
        if ctx not in self._warned:
            self._warned.add(ctx)
            console.print(f"[yellow]{msg}[/yellow]")

    def _extract_value(self, payload: dict, raw: str, metric: str) -> float | None:
        candidates: list[float] = []
        key = metric.lower()

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if key in str(k).lower():
                        candidates.extend(_collect_nums(v))
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)

        if not candidates and raw:
            pattern = re.compile(rf"{re.escape(metric)}[^\d\-]*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
            candidates = [_to_float(m) for m in pattern.findall(raw)]
            candidates = [v for v in candidates if v is not None]

        return max(candidates) if candidates else None


# ── Module-level helpers ─────────────────────────────────────────

def _has_data(series: dict[str, TrendSeries]) -> bool:
    return any(s.values for s in series.values())


def _step_to_seconds(step: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", step.strip().lower())
    if not m:
        return 300
    return max(1, int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)])


def _prom_has_samples(payload: dict) -> bool:
    if payload.get("status") != "success":
        return False
    results = payload.get("data", {}).get("result", [])
    if not isinstance(results, list):
        return False
    return any(
        isinstance(s, dict) and isinstance(s.get("values"), list) and s["values"]
        for s in results
    )


def _collapse_prom(payload: dict, start: int, end: int, step_s: int) -> tuple[list[int], list[float]]:
    if payload.get("status") != "success" or start > end:
        return [], []

    results = payload.get("data", {}).get("result", [])
    if not isinstance(results, list):
        return [], []

    expected = list(range(start, end + 1, max(1, step_s)))
    if not expected:
        expected = [start]
    expected_set = set(expected)

    by_ts: dict[int, list[float]] = {}
    for series in results:
        for pair in (series.get("values", []) if isinstance(series, dict) else []):
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            v = _to_float(pair[1])
            if v is None:
                continue
            ts = int(float(pair[0]))
            if ts not in expected_set:
                offset = round((ts - start) / max(1, step_s))
                snapped = start + (offset * step_s)
                if snapped < start or snapped > end:
                    continue
                ts = snapped
            by_ts.setdefault(ts, []).append(v)

    return expected, [max(by_ts.get(ts, [0.0])) for ts in expected]


def _collect_nums(value: Any) -> list[float]:
    if isinstance(value, dict):
        out = []
        for v in value.values():
            out.extend(_collect_nums(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_collect_nums(v))
        return out
    f = _to_float(value)
    return [f] if f is not None else []


def _to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ── Singleton ────────────────────────────────────────────────────

_provider = MetricsProvider()


def get_provider() -> MetricsProvider:
    return _provider
