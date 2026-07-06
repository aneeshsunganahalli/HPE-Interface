"""
View — Prometheus Query Performance

Displays P12 (Query Latency p99) and P13 (Active Queries) in a table,
with a plain-English diagnostic when latency is high.
"""

from monitor.config import console
from monitor.prometheus.collectors import collect_p12, collect_p13, _prom_metrics_text
from monitor.prometheus.display_utils import score_color, score_bar, status_icon, fmt_score
from rich.panel import Panel
from rich.table import Table
from rich import box


# ── Diagnostic thresholds ─────────────────────────────────────
_LATENCY_WARN_MS   = 500
_LATENCY_CRIT_MS   = 2000
_ACTIVE_WARN       = 10
_ACTIVE_CRIT       = 50


def _status_str(value, warn, crit, unit: str = "") -> str:
    if value is None:
        return "[dim]N/A[/dim]"
    if value >= crit:
        color = "red"
    elif value >= warn:
        color = "yellow"
    else:
        color = "green"
    return f"[{color}]{value:.2f}{unit}[/{color}]"


def _status_icon(value, warn, crit) -> str:
    if value is None:
        return "⚪"
    if value >= crit:
        return "🔴"
    elif value >= warn:
        return "🟡"
    return "🟢"


def _plain_english_diagnostic(latency_ms, active_queries) -> str:
    latency = latency_ms or 0
    active  = active_queries or 0

    if latency >= _LATENCY_CRIT_MS and active >= _ACTIVE_CRIT:
        return (
            "Query engine is severely overloaded. Both latency and concurrent query count "
            "are critically high. Reduce dashboard refresh rates, simplify queries, or "
            "add recording rules to pre-compute expensive aggregations."
        )
    if latency >= _LATENCY_CRIT_MS:
        return (
            "Query latency is critically high. Queries are taking too long to evaluate. "
            "Check for expensive regex matchers, high-cardinality label joins, or queries "
            "over very large time ranges. Consider adding recording rules."
        )
    if active >= _ACTIVE_CRIT:
        return (
            "A very high number of concurrent queries are running. This can saturate CPU "
            "and memory. Review Grafana dashboards for excessive panel counts or short "
            "refresh intervals."
        )
    if latency >= _LATENCY_WARN_MS:
        return (
            "Query latency is elevated. Some queries may be more complex than necessary. "
            "Consider optimizing PromQL expressions or using recording rules for frequently "
            "accessed aggregations."
        )
    if active >= _ACTIVE_WARN:
        return (
            "Moderate number of concurrent queries. This is normal during active dashboard "
            "usage but watch for sustained high counts."
        )
    return "Query engine is performing well — latency and concurrency are within normal range."


def display_query_performance(timeframe: str = "1h") -> None:
    """Render the Query Performance view."""
    console.print()
    console.rule("[bold cyan]Prometheus — Query Performance[/bold cyan]")
    console.print()

    console.print("[dim]Collecting query metrics…[/dim]")
    # Fetch /metrics once for P12
    metrics_text = _prom_metrics_text()
    p12 = collect_p12(metrics_text)
    p13 = collect_p13()
    console.print()

    latency_ms     = p12.get("latency_ms")
    latency_score  = p12.get("value")
    active_queries = p13.get("count")

    # ── Metrics table ─────────────────────────────────────────
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Metric",     style="bold white", ratio=1)
    table.add_column("Value",      width=20, justify="right")
    table.add_column("Score /100", width=12, justify="right")
    table.add_column("Bar",        width=22)
    table.add_column("St",         width=4,  justify="center")
    table.add_column("Detail",     ratio=2)

    # Query Latency
    lat_color = score_color(latency_score, "P12")
    table.add_row(
        "Query Latency (p99)",
        _status_str(latency_ms, _LATENCY_WARN_MS, _LATENCY_CRIT_MS, unit=" ms"),
        f"[{lat_color}]{fmt_score(latency_score)}[/{lat_color}]",
        f"[{lat_color}]{score_bar(latency_score, 20)}[/{lat_color}]",
        status_icon(latency_score, "P12"),
        "[dim]99th percentile query engine latency[/dim]",
    )

    # Active Queries
    aq_val = float(active_queries) if active_queries is not None else None
    table.add_row(
        "Active Queries",
        _status_str(aq_val, _ACTIVE_WARN, _ACTIVE_CRIT, unit="") if aq_val is not None else "[dim]N/A[/dim]",
        "[dim]—[/dim]",
        "[dim]— info —[/dim]",
        _status_icon(aq_val, _ACTIVE_WARN, _ACTIVE_CRIT) if aq_val is not None else "⚪",
        "[dim]Concurrent queries being evaluated[/dim]",
    )

    console.print(table)
    console.print()

    # ── Issue summary & diagnostic ────────────────────────────
    issues: list[str] = []
    if latency_ms is not None:
        if latency_ms >= _LATENCY_CRIT_MS:
            issues.append(f"[red]✗[/red] Query latency critically high ({latency_ms:.2f} ms)")
        elif latency_ms >= _LATENCY_WARN_MS:
            issues.append(f"[yellow]⚠[/yellow] Query latency elevated ({latency_ms:.2f} ms)")

    if active_queries is not None:
        if active_queries >= _ACTIVE_CRIT:
            issues.append(f"[red]✗[/red] Active queries critically high ({active_queries})")
        elif active_queries >= _ACTIVE_WARN:
            issues.append(f"[yellow]⚠[/yellow] Active queries elevated ({active_queries})")

    if issues:
        for issue in issues:
            console.print(f"  {issue}")
        console.print()
        diag_text = _plain_english_diagnostic(latency_ms, active_queries)
        border = "red" if any("✗" in i for i in issues) else "cyan"
        console.print(Panel(
            f"  {diag_text}",
            title="[bold]Diagnosis[/bold]",
            title_align="left",
            border_style=border,
            expand=True,
        ))
    else:
        console.print("  [green]✓ Query engine performing well — latency and concurrency normal.[/green]")

    console.print()
