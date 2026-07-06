from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class PollerPoint:
    ts: int
    cpu_pct: float
    heap_used_bytes: float
    index_total: float | None


class PollerHistoryStore:

    def __init__(self, data_dir: str | Path, bucket_seconds: int = 300) -> None:
        resolved = Path(data_dir)
        if not resolved.is_absolute():
            resolved = Path(__file__).resolve().parent.parent / resolved
        self._data_dir = resolved
        self._bucket_seconds = max(1, bucket_seconds)

    def trends(self, timeframe_minutes: int) -> dict[str, tuple[list[int], list[float]]]:
        if timeframe_minutes <= 0:
            return _empty()

        now = int(time.time())
        start = now - (timeframe_minutes * 60)
        buckets = list(range(start, now + 1, self._bucket_seconds))
        if not buckets:
            buckets = [start]

        points = self._load(start)
        if not points:
            return _empty()

        cpu = [0.0] * len(buckets)
        heap = [0.0] * len(buckets)
        indexing = [0.0] * len(buckets)

        for p in points:
            if p.ts < start or p.ts > now:
                continue
            idx = min((p.ts - start) // self._bucket_seconds, len(buckets) - 1)
            cpu[idx] = max(cpu[idx], p.cpu_pct)
            heap[idx] = max(heap[idx], p.heap_used_bytes)

        prev_total, prev_ts = None, None
        has_indexing = False
        for p in points:
            if p.index_total is None:
                continue
            has_indexing = True
            if prev_total is not None and prev_ts is not None:
                elapsed = max(1, p.ts - prev_ts)
                delta = p.index_total - prev_total
                rate = (delta / elapsed) if delta >= 0 else 0.0
                idx = min(max(0, (p.ts - start) // self._bucket_seconds), len(buckets) - 1)
                indexing[idx] = max(indexing[idx], rate)
            prev_total, prev_ts = p.index_total, p.ts

        return {
            "cpu": (buckets, cpu),
            "heap": (buckets, heap),
            "indexing_rate": (buckets, indexing) if has_indexing else ([], []),
        }

    def _load(self, start_ts: int) -> list[PollerPoint]:
        points: list[PollerPoint] = []
        for path in self._files(start_ts):
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        p = _parse_record(record)
                        if p and p.ts >= start_ts:
                            points.append(p)
            except OSError:
                continue

        if not points:
            return []

        deduped: dict[int, PollerPoint] = {}
        for p in points:
            deduped[p.ts] = p
        return [deduped[ts] for ts in sorted(deduped)]

    def _files(self, start_ts: int) -> list[Path]:
        if not self._data_dir.exists():
            return []
        start_day = datetime.fromtimestamp(start_ts, tz=timezone.utc).date()
        end_day = datetime.now(timezone.utc).date()
        if start_day > end_day:
            start_day = end_day

        paths = []
        day = start_day
        while day <= end_day:
            candidate = self._data_dir / f"metrics_{day.isoformat()}.jsonl"
            if candidate.exists():
                paths.append(candidate)
            day += timedelta(days=1)
        return paths


def _parse_record(record: dict[str, Any]) -> PollerPoint | None:
    ts = _to_int(record.get("ts"))
    if ts is None:
        return None

    nodes = record.get("nodes", {})
    if not isinstance(nodes, dict):
        nodes = {}

    cpus, heaps = [], []
    idx_sum, has_idx = 0.0, False

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        cpu = _to_float(node.get("cpu_pct"))
        if cpu is not None:
            cpus.append(cpu)
        h = _to_float(node.get("heap_used_bytes"))
        if h is not None:
            heaps.append(h)
        it = _to_float(node.get("index_total"))
        if it is not None:
            idx_sum += it
            has_idx = True

    return PollerPoint(
        ts=ts,
        cpu_pct=max(cpus) if cpus else 0.0,
        heap_used_bytes=max(heaps) if heaps else 0.0,
        index_total=idx_sum if has_idx else None,
    )


def _empty() -> dict[str, tuple[list[int], list[float]]]:
    return {"cpu": ([], []), "heap": ([], []), "indexing_rate": ([], [])}


def _to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
