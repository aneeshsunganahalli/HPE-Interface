"""
View — Prometheus Snapshot

Displays all 13 Prometheus self-monitoring metrics in a single table,
grouped by category (Process / System / TSDB / Query).
Shows current values clearly — no score bars.
"""

from monitor.config import console
from monitor.prometheus.collectors import (
    collect_all, METRIC_META, GROUP_COLORS, INFORMATIONAL,
)
from monitor.prometheus.display_utils import status_icon
from rich.table import Table
from rich import box


def _key_value_str(key: str, m: dict) -> str:
    """One-line human-readable raw value for the snapshot table."""
    if not isinstance(m, dict):
        return "N/A"
    try:
        if key == "P1":
            p = m.get("cpu_pct")
            if p is not None:
                pid = m.get("pid", "?")
                return f"{p} %   [dim](PID {pid})[/dim]"
            return m.get("status", "N/A")
        if key == "P2":
            r = m.get("rss_mb")
            p = m.get("rss_pct")
            if r is not None:
                return f"{r} MB   [dim]({p}% of {m.get('total_ram_gb', '?')} GB RAM)[/dim]"
            return m.get("status", "N/A")
        if key == "P3":
            s = m.get("uptime_str", "N/A")
            return s if s != "unavailable" else "[dim]unavailable[/dim]"
        if key == "P4":
            o = m.get("open_fds")
            mx = m.get("max_fds")
            if o is not None and mx is not None:
                return f"{o:,} / {mx:,}   [dim]({m.get('value', 0):.1f}% used)[/dim]"
            return "N/A"
        if key == "P5":
            pct = m.get("disk_pct")
            if pct is not None:
                return (
                    f"{m.get('used_gb', '?')} / {m.get('total_gb', '?')} GB "
                    f"[dim]({pct}%  free: {m.get('free_gb', '?')} GB)[/dim]"
                )
            err = m.get("error", "")
            return f"[dim]{err}[/dim]" if err else "N/A"
        if key == "P6":
            r = m.get("read_mbs")
            w = m.get("write_mbs")
            if r is not None and w is not None:
                return f"Read: {r} MB/s   Write: {w} MB/s"
            return "N/A"
        if key == "P7":
            recv = m.get("recv_mbs")
            sent = m.get("sent_mbs")
            if recv is not None and sent is not None:
                return f"In: {recv} MB/s   Out: {sent} MB/s"
            return "N/A"
        if key == "P8":
            c = m.get("count")
            return f"{c:,}" if c is not None else "N/A"
        if key == "P9":
            c = m.get("count")
            return f"{c:,}" if c is not None else "N/A"
        if key == "P10":
            r = m.get("rate")
            if r is not None:
                return f"{r:,.1f} samples/s"
            t = m.get("total")
            if t is not None:
                return f"{t:,.0f} total   [dim](rate unavailable)[/dim]"
            return "N/A"
        if key == "P11":
            gb = m.get("storage_gb", 0)
            path = m.get("path", "?")
            if gb > 0:
                return f"{gb:.3f} GB   [dim]({path})[/dim]"
            return f"[dim]{path}[/dim]"
        if key == "P12":
            l = m.get("latency_ms")
            return f"{l:.2f} ms" if l is not None else "N/A"
        if key == "P13":
            c = m.get("count")
            return str(c) if c is not None else "0"
    except Exception:
        pass
    return "—"


def display_snapshot(timeframe: str = "1h") -> None:
    """Print the full 13-metric Prometheus snapshot table."""
    snap = collect_all()
    ts = snap.get("timestamp", "—")[:19].replace("T", " ")
    console.rule(
        f"[bold cyan]📊 Prometheus Metrics Snapshot  [dim]{ts}[/dim][/bold cyan]"
    )

    table = Table(
        box=box.ROUNDED,
        header_style="bold cyan",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Group",    style="bold",     width=10)
    table.add_column("Metric",                     width=28)
    table.add_column("Value",                      ratio=1)

    keys = ["P1", "P2", "P3", "P4", "P5", "P6", "P7",
            "P8", "P9", "P10", "P11", "P12", "P13"]

    current_group = None
    for key in keys:
        grp, name, _ = METRIC_META[key]
        gc   = GROUP_COLORS.get(grp, "white")
        m    = snap.get(key, {})
        raw  = _key_value_str(key, m)
        if grp != current_group:
            current_group = grp
            table.add_row(
                f"[bold {gc}]{grp}[/bold {gc}]",
                "", "",
                style="on grey11",
            )

        table.add_row(
            "",
            f"[{gc}]{name}[/{gc}]",
            raw,
        )

    console.print(table)
    console.print()
