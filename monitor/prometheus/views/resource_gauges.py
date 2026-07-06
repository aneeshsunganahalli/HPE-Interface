"""
View — Prometheus Resource Gauges

Displays P1 (CPU), P2 (Memory), P5 (Disk) as large side-by-side
gauge panels with threshold markers.
Mirrors monitor/kafka/views/resource_gauges.py.
"""

from monitor.config import console
from monitor.prometheus.collectors import collect_all, METRIC_META, THRESHOLDS
from monitor.prometheus.display_utils import score_color, fmt_score
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns


def _key_value_str(key: str, m: dict) -> str:
    if not isinstance(m, dict):
        return "N/A"
    try:
        if key == "P1":
            p = m.get("cpu_pct")
            return f"{p} %" if p is not None else m.get("status", "N/A")
        if key == "P2":
            r = m.get("rss_mb")
            p = m.get("rss_pct")
            return f"{r} MB  ({p} % of RAM)" if r is not None else m.get("status", "N/A")
        if key == "P5":
            return (
                f"{m.get('used_gb', '?')} GB / {m.get('total_gb', '?')} GB "
                f"({m.get('disk_pct', '?')} %)"
            )
    except Exception:
        pass
    return "—"


def _gauge_panel(key: str, m: dict) -> Panel:
    _, name, unit = METRIC_META[key]
    score      = m.get("value") if isinstance(m, dict) else None
    color      = score_color(score, key)
    raw        = _key_value_str(key, m)
    warn, crit = THRESHOLDS.get(key, (50, 75))

    bar_w  = 40
    filled = max(0, min(int(((score or 0) / 100.0) * bar_w), bar_w))

    warn_pos = int((warn / 100.0) * bar_w)
    crit_pos = int((crit / 100.0) * bar_w)
    axis     = list(" " * (bar_w + 2))
    axis[warn_pos] = "↑"
    axis[crit_pos] = "↑"
    axis_str = "".join(axis)

    body = Text()
    body.append("\n  ")
    body.append("█" * filled,           style=color)
    body.append("░" * (bar_w - filled), style="dim")
    body.append("\n")
    body.append(f"  {axis_str}\n",      style="dim")
    body.append(f"  warn={warn}    crit={crit}\n\n", style="dim")
    body.append("  Value : ", style="bold")
    body.append(f"{raw}\n",   style="white")

    # Extra detail for disk
    if key == "P5" and isinstance(m, dict) and m.get("disk_pct") is not None:
        body.append(f"\n  Path : ", style="bold")
        body.append(f"{m.get('path', '?')}\n", style="white")
        body.append(f"  Free : ", style="bold")
        body.append(f"{m.get('free_gb', '?')} GB\n", style="white")

    panel_width = 58 if key == "P5" else 54
    return Panel(
        body,
        title=f"[bold cyan]{name}[/bold cyan]",
        border_style=color,
        padding=(0, 2),
        width=panel_width,
    )


def display_resource_gauges(timeframe: str = "1h") -> None:
    """Display P1, P2, P5 as large side-by-side gauge panels."""
    snap = collect_all()
    console.rule("[bold cyan]⚙  Prometheus Resource Gauges  (CPU / Memory / Disk)[/bold cyan]")
    panels = [
        _gauge_panel("P1", snap.get("P1", {})),
        _gauge_panel("P2", snap.get("P2", {})),
        _gauge_panel("P5", snap.get("P5", {})),
    ]
    console.print(Columns(panels, equal=True, expand=True))
    console.print(
        "[dim]  CPU and Memory are Prometheus-process-specific (psutil).\n"
        "  Disk measures the partition hosting the Prometheus TSDB data directory.[/dim]"
    )
