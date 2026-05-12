import sys
import time
import datetime
import re

import click

from extras.config import console
from extras.metrics import get_provider
from extras.menus import main_menu, opensearch_menu, VIEWS, CURSOR, CURSOR_STYLE, HIGHLIGHT_STYLE
from extras.views.quick_summary import display_quick_summary
from extras.utils import press_enter


@click.command()
@click.option("--timeframe", default="1h", show_default=True,
              help="Time window (real-time, 30m, 6h, 2d).")
@click.option("--source", type=click.Choice(["auto", "poller", "prometheus"], case_sensitive=False),
              default=None, help="Historical trend source.")
@click.option("--watch", type=int, default=None,
              help="Auto-refresh interval in seconds.")
@click.option("--summary", is_flag=True, default=False,
              help="Jump straight to Quick Summary.")
@click.option("--service", type=click.Choice(["opensearch", "kafka", "logstash"], case_sensitive=False),
              default=None, help="Service to monitor.")
@click.option("--query", default="*", help="Query string for Log Browser.")
@click.option("--level", type=click.Choice(["error", "warn", "info", "debug", "critical"], case_sensitive=False),
              default=None, help="Log level filter.")
@click.option("--spike-ts", default=None,
              help="ISO timestamp for Root Cause Analysis.")
def cli(timeframe, source, watch, summary, service, query, level, spike_ts):
    """OpenSearch Cluster Monitor — a terminal-based health checker."""

    if not re.fullmatch(r"(real-time|\d+[mhd])", timeframe, re.IGNORECASE):
        raise click.BadParameter(
            f"'{timeframe}' is not valid. Use 'real-time' or number+m/h/d (e.g. 30m, 6h, 7d).",
            param_hint="'--timeframe'",
        )
    timeframe = timeframe.lower()

    if source:
        get_provider().set_source(source)

    if service in ("kafka", "logstash"):
        console.print(f"\n[yellow]⚠  {service.title()} monitoring is coming soon.[/yellow]")
        sys.exit(0)

    if summary:
        if watch:
            _watch(display_quick_summary, watch, timeframe=timeframe)
        else:
            display_quick_summary(timeframe=timeframe)
            press_enter()
        return

    if watch:
        from simple_term_menu import TerminalMenu
        from rich.panel import Panel

        console.clear()
        console.print()
        console.print(Panel.fit(
            "[bold cyan]OpenSearch Monitor — Watch Mode[/bold cyan]\n"
            f"[dim]Select a view to auto-refresh every {watch}s[/dim]",
            border_style="cyan",
        ))
        console.print()

        options = [label for label, _ in VIEWS]
        menu = TerminalMenu(options, menu_cursor=CURSOR,
                            menu_cursor_style=CURSOR_STYLE, menu_highlight_style=HIGHLIGHT_STYLE)
        choice = menu.show()
        if choice is None:
            return

        label, view_fn = VIEWS[choice]
        kwargs = {"timeframe": timeframe}
        # if label == "Log Browser":
        #     kwargs.update(query_str=query, level=level)
        # elif label == "Root Cause Analysis":
        #     kwargs = {"spike_ts": spike_ts}

        _watch(view_fn, watch, **kwargs)
        return

    if service == "opensearch":
        opensearch_menu(timeframe=timeframe, query=query, level=level, spike_ts=spike_ts)
    else:
        main_menu(timeframe=timeframe, query=query, level=level, spike_ts=spike_ts)


def _watch(view_fn, interval: int, **kwargs):
    try:
        while True:
            console.clear()
            view_fn(**kwargs)
            now = datetime.datetime.now().strftime("%H:%M:%S")
            console.print(f"\n[dim]Last updated: {now} — refreshing in {interval}s (Ctrl+C to stop)[/dim]")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


if __name__ == "__main__":
    cli()
