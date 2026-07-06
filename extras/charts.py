from __future__ import annotations

from datetime import datetime

from extras.config import console
from extras.metrics import TrendSeries
from extras.utils import format_bytes


_LINE_CHARS = "⠀⡀⣀⣄⣤⣴⣶⣾⣿"  # braille progression for sub-cell resolution
_DEFAULT_WIDTH = 60
_DEFAULT_HEIGHT = 10


def line_chart(
    series: TrendSeries,
    width: int | None = None,
    height: int = _DEFAULT_HEIGHT,
    color: str = "bright_cyan",
) -> str:
    if not series.values:
        return "[dim]no data[/dim]"

    w = width or _pick_width()
    values, timestamps = _downsample(series, w)
    if not values:
        return "[dim]no data[/dim]"

    lo, hi = min(values), max(values)
    span = hi - lo

    # Normalize to 0..height range
    if span <= 0:
        norm = [height // 2] * len(values)
    else:
        norm = [int(round(((v - lo) / span) * (height - 1))) for v in values]

    # Build the grid
    label_w = max(len(format_value(series, hi)), len(format_value(series, lo)), 6)
    tick_rows = {height - 1, max(0, int(round((height - 1) * 0.75))),
                 max(0, int(round((height - 1) * 0.5))),
                 max(0, int(round((height - 1) * 0.25))), 0}

    lines: list[str] = []
    for row in range(height - 1, -1, -1):
        axis_val = lo + (span * row / max(1, height - 1)) if span > 0 else hi
        label = format_value(series, axis_val)
        prefix = f"{label:>{label_w}} │ " if row in tick_rows else f"{'':>{label_w}} │ "

        chars = []
        for i, n in enumerate(norm):
            if n == row:
                chars.append("●")
            elif i > 0 and _between(row, norm[i - 1], n):
                chars.append("│" if abs(norm[i - 1] - n) > 1 else "·")
            else:
                chars.append(" ")

        lines.append(f"[dim]{prefix}[/dim][{color}]{''.join(chars)}[/{color}]")

    # X-axis
    lines.append(f"[dim]{'':>{label_w}} └{'─' * len(norm)}[/dim]")

    start_ts = _fmt_ts(timestamps[0]) if timestamps else ""
    end_ts = _fmt_ts(timestamps[-1]) if len(timestamps) >= 2 else ""
    if start_ts and end_ts:
        gap = max(1, len(norm) - len(start_ts) - len(end_ts))
        lines.append(f"[dim]{'':>{label_w}}  {start_ts}{' ' * gap}{end_ts}[/dim]")
    lines.append(f"[dim]{'':>{label_w}}  older → newer[/dim]")

    return "\n".join(lines)


def format_value(series: TrendSeries, value: float) -> str:
    if series.unit == "%":
        return f"{value:.1f}%"
    if series.unit == "bytes":
        return format_bytes(value)
    if series.unit == "ops/s":
        if value >= 100:
            return f"{value:.0f}/s"
        if value >= 10:
            return f"{value:.1f}/s"
        if value >= 1:
            return f"{value:.2f}/s"
        if value > 0:
            return f"{value:.4f}/s"
        return "0/s"
    return f"{value:.2f}"


def series_average(series: TrendSeries) -> float:
    return sum(series.values) / len(series.values) if series.values else 0.0


# ── Internal ─────────────────────────────────────────────────────

def _pick_width() -> int:
    tw = getattr(console, "width", 120) or 120
    return max(36, min(_DEFAULT_WIDTH, tw - 28))


def _downsample(series: TrendSeries, width: int) -> tuple[list[float], list[int]]:
    n = len(series.values)
    if n <= 0:
        return [], []
    if n <= width:
        indices = list(range(n))
    else:
        step = (n - 1) / (width - 1)
        indices = [round(i * step) for i in range(width)]

    vals = [series.values[i] for i in indices]
    ts = [series.timestamps[i] for i in indices] if len(series.timestamps) == n else []
    return vals, ts


def _between(row: int, prev: int, curr: int) -> bool:
    lo, hi = min(prev, curr), max(prev, curr)
    return lo < row < hi


def _fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return ""
