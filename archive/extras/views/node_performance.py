from __future__ import annotations
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich import box

from archive.extras.config import console, CPU_WARN, CPU_CRIT, HEAP_WARN, HEAP_CRIT, DISK_WARN, DISK_CRIT
from archive.extras.metrics import get_provider
from archive.extras.client import node_stats
from archive.extras.utils import format_bytes, status_symbol, status_color

PA_IO_WAIT_WARN = 20.0


def _diagnose(cpu: float, disk: float, disk_util: float | None, io_wait: float | None) -> str:
    if io_wait is not None and io_wait >= PA_IO_WAIT_WARN and cpu >= CPU_WARN:
        return "CPU looks high, but storage wait is the real issue. Threads are blocked on disk I/O."

    if disk_util is not None and disk_util >= DISK_WARN and disk >= DISK_WARN:
        return "Disk is the bottleneck. Indexing/merge workloads are saturating storage bandwidth."

    if cpu >= CPU_WARN and disk < DISK_WARN:
        return "Node is compute-bound. Indexing/search workload is consuming most CPU cycles."

    if disk >= DISK_WARN:
        return "Node is storage-bound. Disk pressure increases index and query latency."

    return "Pressure is elevated, but root cause is inconclusive from current telemetry."


def _fmt_signal(value: float | None, unit: str | None = "%") -> str:
    if value is None:
        return "[dim]n/a[/dim]"
    return f"{value:.1f}{unit}" if unit else f"{value:.1f}"


def display_node_performance(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Node Performance[/bold cyan]")
    console.print()

    ns = node_stats()
    if not ns or "nodes" not in ns:
        console.print("[red]Could not retrieve node stats.[/red]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Node", style="bold white", ratio=1)
    table.add_column("CPU", width=10, justify="right")
    table.add_column("", width=3, justify="center")
    table.add_column("JVM Heap", width=22, justify="right")
    table.add_column("", width=3, justify="center")
    table.add_column("System RAM", width=22, justify="right")
    table.add_column("Disk (fs.total)", width=22, justify="right")
    table.add_column("", width=3, justify="center")

    issues = []
    activity = []
    diagnostics: list[dict[str, Any]] = []

    for nid, n in ns["nodes"].items():
        name = n.get("name", nid[:8])
        os_info = n.get("os", {})

        cpu = os_info.get("cpu", {}).get("percent", 0)
        cc = status_color(cpu, CPU_WARN, CPU_CRIT)

        jvm = n.get("jvm", {}).get("mem", {})
        hu, hm = jvm.get("heap_used_in_bytes", 0), jvm.get("heap_max_in_bytes", 0)
        hp = (hu / hm * 100) if hm > 0 else 0
        hc = status_color(hp, HEAP_WARN, HEAP_CRIT)

        mem = os_info.get("mem", {})
        mu, mt = mem.get("used_in_bytes", 0), mem.get("total_in_bytes", 0)

        fs = n.get("fs", {}).get("total", {})
        dt, da = fs.get("total_in_bytes", 0), fs.get("available_in_bytes", 0)
        du = dt - da
        dp = (du / dt * 100) if dt > 0 else 0
        dc = status_color(dp, DISK_WARN, DISK_CRIT)

        table.add_row(
            name,
            f"[{cc}]{cpu}%[/{cc}]", status_symbol(cpu, CPU_WARN, CPU_CRIT),
            f"[{hc}]{format_bytes(hu)} / {format_bytes(hm)}[/{hc}]", status_symbol(hp, HEAP_WARN, HEAP_CRIT),
            f"[dim]{format_bytes(mu)} / {format_bytes(mt)}[/dim]",
            f"[{dc}]{format_bytes(du)} / {format_bytes(dt)}[/{dc}]", status_symbol(dp, DISK_WARN, DISK_CRIT),
        )

        idx_total = n.get("indices", {}).get("indexing", {}).get("index_total", 0)
        qry_total = n.get("indices", {}).get("search", {}).get("query_total", 0)
        activity.append((name, idx_total, qry_total))

        if cpu >= CPU_CRIT:
            issues.append(f"[red]✗[/red]  {name} — critically high CPU ({cpu}%)")
        elif cpu >= CPU_WARN:
            issues.append(f"[yellow]⚠[/yellow]  {name} — elevated CPU ({cpu}%)")

        if hp >= HEAP_CRIT:
            issues.append(f"[red]✗[/red]  {name} — JVM Heap at {hp:.0f}% — risk of OutOfMemory")
        elif hp >= HEAP_WARN:
            issues.append(f"[yellow]⚠[/yellow]  {name} — JVM Heap at {hp:.0f}%")

        if dp >= DISK_CRIT:
            issues.append(f"[red]✗[/red]  {name} — critically full disk ({dp:.0f}%)")
        elif dp >= DISK_WARN:
            issues.append(f"[yellow]⚠[/yellow]  {name} — disk getting full ({dp:.0f}%)")

        if cpu >= CPU_WARN or dp >= DISK_WARN:
            pa = get_provider().bottleneck_metrics(name)
            diagnostics.append({
                "node": name,
                "severity": "critical" if (cpu >= CPU_CRIT or dp >= DISK_CRIT) else "warning",
                "cpu": cpu, "disk": dp,
                "disk_util": pa.get("disk_utilization"),
                "io_wait": pa.get("io_tot_wait"),
                "explanation": _diagnose(cpu, dp, pa.get("disk_utilization"), pa.get("io_tot_wait")),
            })

    console.print(table)
    console.print()

    # Activity table
    act = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", expand=True)
    act.add_column("Node", style="bold white", ratio=1)
    act.add_column("Indexing Ops", width=18, justify="right", style="cyan")
    act.add_column("Search Queries", width=18, justify="right", style="magenta")
    for name, idx, qry in activity:
        act.add_row(name, f"{idx:,}" if idx else "[dim]0[/dim]", f"{qry:,}" if qry else "[dim]0[/dim]")
    console.print(Panel(act, title="[bold]Indexing & Search Activity[/bold]  [dim](cumulative)[/dim]",
                        title_align="left", border_style="cyan", expand=True))
    console.print()

    # Issues
    if issues:
        for i in issues:
            console.print(f"  {i}")
    else:
        console.print("  [green]✓  All nodes healthy — no performance concerns.[/green]")
    console.print()

    # Diagnostics
    if diagnostics:
        crit = sum(1 for d in diagnostics if d["severity"] == "critical")
        console.print(Panel(
            f"  {len(diagnostics)} node(s) crossed CPU/Disk thresholds.\n"
            f"  Critical: {crit}    Warning: {len(diagnostics) - crit}\n"
            "  Drill-down below uses Performance Analyzer metrics.",
            title="[bold]Diagnostic[/bold]", title_align="left", border_style="cyan", expand=True,
        ))

        dt = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", expand=True)
        dt.add_column("Node", style="bold white", ratio=1)
        dt.add_column("Pressure", width=10, justify="center")
        dt.add_column("PA Signals", width=34)
        dt.add_column("Plain English Diagnosis", ratio=3)

        for d in diagnostics:
            pressure = "[red]critical[/red]" if d["severity"] == "critical" else "[yellow]warning[/yellow]"
            signals = f"Disk_Utilization={_fmt_signal(d['disk_util'])}  IO_TotWait={_fmt_signal(d['io_wait'], unit=None)}"
            dt.add_row(d["node"], pressure, signals, d["explanation"])

        console.print(dt)
    else:
        console.print(Panel(
            "  [green]No CPU or disk bottlenecks detected.[/green]",
            title="[bold]Diagnostic[/bold]", title_align="left", border_style="green", expand=True,
        ))
    console.print()
