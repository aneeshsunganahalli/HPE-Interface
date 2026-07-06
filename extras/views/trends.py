from __future__ import annotations

from rich.panel import Panel

from extras.config import CPU_WARN, CPU_CRIT, console
from extras.metrics import TrendSeries, get_provider
from extras.charts import line_chart, format_value, series_average
from extras.utils import is_realtime, timeframe_to_prom_range

CHART_COLOR = "bright_cyan"


def _readout(key: str, series: TrendSeries) -> str:
    if not series.values:
        return "No data available in this window."

    if key == "cpu":
        if series.peak >= CPU_CRIT:
            return "Critical CPU spike detected. Investigate query/indexing pressure immediately."
        if series.peak >= CPU_WARN:
            return "Warning CPU spike detected. Monitor sustained load and hot shards."
        return "CPU trend is stable with no major spike."

    if key == "heap":
        if series.latest > 0 and series.peak >= series.latest * 1.4:
            return "Heap spike much higher than current level. Check for GC or burst traffic."
        return "Heap trend is steady relative to current usage."

    if key == "indexing_rate":
        if series.peak >= max(series.latest * 1.5, 1.0):
            return "Burst indexing detected. Validate ingest pipeline throughput."
        return "Indexing rate is consistent across the selected window."

    return "Trend captured."


def display_trends(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Historical Trends[/bold cyan]")
    console.print()

    effective = timeframe_to_prom_range(timeframe)
    note = "real-time requested → using 1h history" if is_realtime(timeframe) else f"--timeframe {effective}"

    source, data = get_provider().trends_with_source(timeframe)
    cpu = data.get("cpu", TrendSeries("CPU", [], [], "%"))
    heap = data.get("heap", TrendSeries("JVM Heap", [], [], "bytes"))
    idx = data.get("indexing_rate", TrendSeries("Indexing Rate", [], [], "ops/s"))

    if not cpu.values and not heap.values and not idx.values:
        console.print(Panel(
            "  No trend data available.\n"
            "  Verify Prometheus connectivity and OpenSearch metric ingestion.",
            title="[bold]Historical Trends[/bold]", title_align="left",
            border_style="yellow", expand=False,
        ))
        console.print()
        return

    source_labels = {
        "poller": "Poller JSONL (5m max buckets)",
        "mixed": "Mixed: poller JSONL + Prometheus fallback",
        "prometheus": "Prometheus (5m max_over_time buckets)",
    }

    console.print(Panel(
        f"  Source        : {source_labels.get(source, 'Unavailable')}\n"
        f"  Time Window   : {effective} ({note})\n"
        f"  Peak CPU      : {format_value(cpu, cpu.peak)}\n"
        f"  Peak JVM Heap : {format_value(heap, heap.peak)}\n"
        f"  Peak Indexing : {format_value(idx, idx.peak)}",
        title="[bold]Summary[/bold]", title_align="left", border_style="cyan", expand=True,
    ))
    console.print()

    for key, series in [("cpu", cpu), ("heap", heap), ("indexing_rate", idx)]:
        latest = format_value(series, series.latest) if series.values else "—"
        peak = format_value(series, series.peak) if series.values else "—"
        avg = format_value(series, series_average(series)) if series.values else "—"
        minimum = format_value(series, min(series.values)) if series.values else "—"

        chart = line_chart(series, color=CHART_COLOR)
        details = (
            f"[bold]Latest:[/bold] {latest}    "
            f"[bold]Peak:[/bold] {peak}    "
            f"[bold]Average:[/bold] {avg}    "
            f"[bold]Min:[/bold] {minimum}\n"
            f"[bold]Readout:[/bold] {_readout(key, series)}"
        )

        console.print(Panel(
            f"{chart}\n\n{details}",
            title=f"[bold]{series.label}[/bold]", title_align="left",
            border_style=CHART_COLOR, expand=True,
        ))
        console.print()
