import datetime

from rich.panel import Panel
from rich.table import Table
from rich import box

from archive.extras.config import console
from archive.extras.client import data_streams
from archive.extras.utils import format_bytes, parse_size_string

STALE_WARN_MINUTES = 60
STALE_CRIT_MINUTES = 240


def _format_age(ts_ms: int | None) -> tuple[str, str]:
    if not ts_ms:
        return "—", "dim"

    last = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc)
    delta = datetime.datetime.now(tz=datetime.timezone.utc) - last
    mins = int(delta.total_seconds() / 60)

    if mins < 1:
        label = "< 1 min ago"
    elif mins < 60:
        label = f"{mins} min ago"
    elif mins < 1440:
        h, m = mins // 60, mins % 60
        label = f"{h}h {m}m ago" if m else f"{h}h ago"
    else:
        label = f"{mins // 1440}d ago"

    if mins >= STALE_CRIT_MINUTES:
        return label, "red"
    if mins >= STALE_WARN_MINUTES:
        return label, "yellow"
    return label, "green"


def display_data_streams(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Data Streams[/bold cyan]")
    console.print()

    result = data_streams()
    streams = result.get("data_streams", []) if result else []

    if not streams:
        console.print(Panel(
            "  No data streams found.\n"
            "  [dim]Data streams are used for time-series data (logs, metrics, traces).[/dim]",
            title="[bold]Data Streams[/bold]", title_align="left",
            border_style="cyan", expand=False,
        ))
        console.print()
        return

    def _size(s: dict) -> int:
        raw = s.get("store_size") or s.get("store_size_bytes", "0")
        return raw if isinstance(raw, int) else int(parse_size_string(str(raw)))

    streams.sort(key=_size, reverse=True)

    console.print(Panel(
        f"  Total streams : {len(streams)}\n"
        f"  Total size    : {format_bytes(sum(_size(s) for s in streams))}",
        title="[bold]Data Streams Summary[/bold]", title_align="left",
        border_style="cyan", expand=False,
    ))
    console.print()

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Stream Name", style="bold white", ratio=2)
    table.add_column("Size", style="yellow", width=12, justify="right")
    table.add_column("Backing Indices", style="dim", width=10, justify="center")
    table.add_column("Last Data", width=18, justify="right")
    table.add_column("Status", width=4, justify="center")

    alerts = []
    for i, s in enumerate(streams, 1):
        name = s.get("name", "—")
        age_label, age_color = _format_age(s.get("maximum_timestamp"))

        sym_map = {"red": "[red]✗[/red]", "yellow": "[yellow]⚠[/yellow]", "green": "[green]✓[/green]"}
        sym = sym_map.get(age_color, "[dim]—[/dim]")

        if age_color == "red":
            alerts.append(f"[red]✗[/red]  [bold]{name}[/bold] — last data [red]{age_label}[/red]. Pipeline may have stopped.")
        elif age_color == "yellow":
            alerts.append(f"[yellow]⚠[/yellow]  [bold]{name}[/bold] — last data [yellow]{age_label}[/yellow]. Monitor pipeline.")

        table.add_row(str(i), name, format_bytes(_size(s)),
                      str(len(s.get("indices", []))), f"[{age_color}]{age_label}[/{age_color}]", sym)

    console.print(table)
    console.print()

    if alerts:
        console.rule("[bold yellow]Pipeline Alerts[/bold yellow]")
        console.print()
        for a in alerts:
            console.print(f"  {a}")
        console.print()
        console.print(Panel(
            "  [dim]These warnings mean the upstream pipeline (Logstash, Kafka, Beats)\n"
            "  has slowed or stopped. Check your pipeline — OpenSearch itself is healthy.[/dim]",
            title="[bold cyan]What to check[/bold cyan]", title_align="left",
            border_style="cyan", expand=False,
        ))
    else:
        console.print("  [green]✓  All streams are receiving data — pipelines look healthy.[/green]")
    console.print()
