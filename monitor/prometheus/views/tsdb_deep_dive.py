"""
View — Prometheus TSDB Deep Dive

Displays P8 (Head Series), P9 (Head Chunks), P10 (Samples/sec),
and P11 (Storage Size) in a table, with a diagnostic panel when
TSDB pressure is detected.
"""

from monitor.config import console
from monitor.prometheus.collectors import (
    collect_p8, collect_p9, collect_p10, collect_p11,
    _prom_metrics_text,
)
from rich.panel import Panel
from rich.table import Table
from rich import box


# ── Diagnostic thresholds ─────────────────────────────────────
_HEAD_SERIES_WARN  = 500_000
_HEAD_SERIES_CRIT  = 2_000_000
_HEAD_CHUNKS_WARN  = 1_000_000
_HEAD_CHUNKS_CRIT  = 5_000_000
_SAMPLES_WARN      = 50_000
_SAMPLES_CRIT      = 200_000
_STORAGE_WARN_GB   = 50
_STORAGE_CRIT_GB   = 200


def _status_str(value, warn, crit, fmt: str = "{:,.0f}") -> str:
    """Colorize a value based on warning/critical thresholds."""
    if value is None:
        return "[dim]N/A[/dim]"
    if value >= crit:
        color = "red"
    elif value >= warn:
        color = "yellow"
    else:
        color = "green"
    return f"[{color}]{fmt.format(value)}[/{color}]"


def _status_icon(value, warn, crit) -> str:
    if value is None:
        return "⚪"
    if value >= crit:
        return "🔴"
    elif value >= warn:
        return "🟡"
    return "🟢"


def _plain_english_diagnostic(series, chunks, rate, storage_gb) -> str:
    """Generate a plain-English diagnostic for TSDB health."""
    series  = series  or 0
    chunks  = chunks  or 0
    rate    = rate    or 0
    storage = storage_gb or 0

    if series >= _HEAD_SERIES_CRIT and rate >= _SAMPLES_CRIT:
        return (
            "TSDB is under heavy pressure. Both head series count and ingestion rate are "
            "critically high. Consider reducing the number of scrape targets, shortening "
            "label cardinality, or adding federation to distribute the load."
        )
    if series >= _HEAD_SERIES_CRIT:
        return (
            "Head series count is very high. This increases memory usage and compaction time. "
            "Review your scrape configs for high-cardinality labels or unnecessary targets."
        )
    if rate >= _SAMPLES_CRIT:
        return (
            "Sample ingestion rate is critically high. Prometheus may struggle to keep up "
            "with writes. Consider reducing scrape frequency or the number of metrics exposed."
        )
    if storage >= _STORAGE_CRIT_GB:
        return (
            "TSDB storage is very large. This can slow down startup and compaction. "
            "Consider reducing retention (--storage.tsdb.retention.time) or using "
            "remote write to offload older data."
        )
    if chunks >= _HEAD_CHUNKS_CRIT:
        return (
            "Head chunk count is very high. This correlates with memory pressure. "
            "Reduce scrape interval or target count to lower chunk creation rate."
        )
    if series >= _HEAD_SERIES_WARN:
        return (
            "Head series count is elevated. Monitor memory usage closely — high series "
            "counts increase RAM requirements proportionally."
        )
    if storage >= _STORAGE_WARN_GB:
        return (
            "TSDB storage is growing. Keep an eye on disk free space and consider "
            "adjusting retention settings if growth continues."
        )
    if rate >= _SAMPLES_WARN:
        return (
            "Ingestion rate is moderate to high. This is normal for large clusters "
            "but keep monitoring for sustained growth."
        )
    return "TSDB is operating within normal parameters."


def display_tsdb_deep_dive(timeframe: str = "1h") -> None:
    """Render the TSDB Deep Dive view."""
    console.print()
    console.rule("[bold cyan]Prometheus — TSDB Deep Dive[/bold cyan]")
    console.print()

    console.print("[dim]Collecting TSDB metrics…[/dim]")
    # Fetch /metrics once and share across P8 and P9
    metrics_text = _prom_metrics_text()
    p8  = collect_p8(metrics_text)
    p9  = collect_p9(metrics_text)
    p10 = collect_p10()
    p11 = collect_p11()
    console.print()

    series_count  = p8.get("count")
    chunks_count  = p9.get("count")
    sample_rate   = p10.get("rate")
    storage_gb    = p11.get("storage_gb")

    # ── Metrics table ─────────────────────────────────────────
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Metric",  style="bold white", ratio=1)
    table.add_column("Value",   width=28, justify="right")
    table.add_column("St",      width=4,  justify="center")
    table.add_column("Detail",  ratio=2)

    # Head Series
    table.add_row(
        "Head Series",
        _status_str(series_count, _HEAD_SERIES_WARN, _HEAD_SERIES_CRIT),
        _status_icon(series_count, _HEAD_SERIES_WARN, _HEAD_SERIES_CRIT),
        "[dim]Active time series in memory[/dim]",
    )

    # Head Chunks
    table.add_row(
        "Head Chunks",
        _status_str(chunks_count, _HEAD_CHUNKS_WARN, _HEAD_CHUNKS_CRIT),
        _status_icon(chunks_count, _HEAD_CHUNKS_WARN, _HEAD_CHUNKS_CRIT),
        "[dim]Active chunks in TSDB head block[/dim]",
    )

    # Samples/sec
    p10_detail = "[dim]Ingestion rate into TSDB[/dim]"
    if sample_rate is None and p10.get("total") is not None:
        p10_detail = f"[dim]Rate unavailable — total appended: {p10['total']:,.0f}[/dim]"
    table.add_row(
        "Samples Appended/sec",
        _status_str(sample_rate, _SAMPLES_WARN, _SAMPLES_CRIT, fmt="{:,.1f}"),
        _status_icon(sample_rate, _SAMPLES_WARN, _SAMPLES_CRIT),
        p10_detail,
    )

    # Storage Size
    table.add_row(
        "Storage Size",
        _status_str(storage_gb, _STORAGE_WARN_GB, _STORAGE_CRIT_GB, fmt="{:.3f} GB"),
        _status_icon(storage_gb, _STORAGE_WARN_GB, _STORAGE_CRIT_GB),
        f"[dim]Data dir: {p11.get('path', '?')}[/dim]",
    )

    console.print(table)
    console.print()

    # ── Issue summary & diagnostic ────────────────────────────
    issues: list[str] = []
    if series_count is not None:
        if series_count >= _HEAD_SERIES_CRIT:
            issues.append(f"[red]✗[/red] Head series critically high ({series_count:,})")
        elif series_count >= _HEAD_SERIES_WARN:
            issues.append(f"[yellow]⚠[/yellow] Head series elevated ({series_count:,})")

    if chunks_count is not None:
        if chunks_count >= _HEAD_CHUNKS_CRIT:
            issues.append(f"[red]✗[/red] Head chunks critically high ({chunks_count:,})")
        elif chunks_count >= _HEAD_CHUNKS_WARN:
            issues.append(f"[yellow]⚠[/yellow] Head chunks elevated ({chunks_count:,})")

    if sample_rate is not None:
        if sample_rate >= _SAMPLES_CRIT:
            issues.append(f"[red]✗[/red] Ingestion rate critically high ({sample_rate:,.1f} samples/s)")
        elif sample_rate >= _SAMPLES_WARN:
            issues.append(f"[yellow]⚠[/yellow] Ingestion rate elevated ({sample_rate:,.1f} samples/s)")

    if storage_gb is not None:
        if storage_gb >= _STORAGE_CRIT_GB:
            issues.append(f"[red]✗[/red] Storage critically large ({storage_gb:.1f} GB)")
        elif storage_gb >= _STORAGE_WARN_GB:
            issues.append(f"[yellow]⚠[/yellow] Storage elevated ({storage_gb:.1f} GB)")

    if issues:
        for issue in issues:
            console.print(f"  {issue}")
        console.print()
        diag_text = _plain_english_diagnostic(series_count, chunks_count, sample_rate, storage_gb)
        border = "red" if any("✗" in i for i in issues) else "cyan"
        console.print(Panel(
            f"  {diag_text}",
            title="[bold]Diagnosis[/bold]",
            title_align="left",
            border_style=border,
            expand=True,
        ))
    else:
        console.print("  [green]✓ TSDB operating within normal parameters.[/green]")

    console.print()
