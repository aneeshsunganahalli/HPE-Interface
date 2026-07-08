import sys

from rich.panel import Panel
from simple_term_menu import TerminalMenu

from archive.extras.config import console
from archive.extras.views.quick_summary import display_quick_summary
from archive.extras.views.trends import display_trends
from archive.extras.views.cluster_health import display_cluster_health
from archive.extras.views.index_deep_dive import display_index_deep_dive
from archive.extras.views.node_performance import display_node_performance
from archive.extras.views.shard_overview import display_shard_overview
# from monitor_v2.views.data_streams import display_data_streams
# from monitor_v2.views.log_browser import display_log_browser
# from monitor_v2.views.root_cause import display_root_cause
from archive.extras.utils import press_enter

CURSOR = "❯ "
CURSOR_STYLE = ("fg_cyan", "bold")
HIGHLIGHT_STYLE = ("fg_cyan", "bold")

VIEWS = [
    ("Quick Summary", display_quick_summary),
    ("Historical Trends", display_trends),
    ("Cluster Health", display_cluster_health),
    ("Index Deep Dive", display_index_deep_dive),
    ("Node Performance", display_node_performance),
    ("Shard Overview", display_shard_overview),
    # ("Log Browser", display_log_browser),
    # ("Root Cause Analysis", display_root_cause),
    # ("Data Streams", display_data_streams),
]

SERVICE_OPTIONS = [
    "OpenSearch",
    "Kafka          (coming soon)",
    "Logstash       (coming soon)",
    "---",
    "All Services   (coming soon)",
    "---",
    "Exit",
]


def main_menu(timeframe="1h", query="*", level=None, spike_ts=None):
    while True:
        console.clear()
        console.print()
        console.print(Panel.fit(
            "[bold cyan]Cluster Monitor[/bold cyan]\n"
            "[dim]Use arrow keys, press Enter to select[/dim]",
            border_style="cyan",
        ))
        console.print()

        menu = TerminalMenu(SERVICE_OPTIONS, menu_cursor=CURSOR,
                            menu_cursor_style=CURSOR_STYLE, menu_highlight_style=HIGHLIGHT_STYLE)
        choice = menu.show()

        if choice is None or choice == 6:
            console.print("[bold green]Goodbye![/bold green]")
            sys.exit(0)
        elif choice == 0:
            opensearch_menu(timeframe=timeframe, query=query, level=level, spike_ts=spike_ts)
        elif choice in (1, 2, 4):
            console.print("\n[yellow]⚠  This service is coming soon.[/yellow]")
            press_enter()


def opensearch_menu(timeframe="1h", query="*", level=None, spike_ts=None):
    while True:
        console.clear()
        console.print()
        console.print(Panel.fit(
            "[bold cyan]OpenSearch Monitor[/bold cyan]\n"
            "[dim]Use arrow keys, Enter to select[/dim]",
            border_style="cyan",
        ))
        console.print()

        labels = [label for label, _ in VIEWS]
        options = labels + ["---", "Back to Main Menu"]
        menu = TerminalMenu(options, menu_cursor=CURSOR,
                            menu_cursor_style=CURSOR_STYLE, menu_highlight_style=HIGHLIGHT_STYLE)
        choice = menu.show()

        if choice is None or choice == len(options) - 1:
            return

        if options[choice] == "---":
            continue

        if choice < len(VIEWS):
            label, view_fn = VIEWS[choice]
            console.clear()
            try:
                # if label == "Log Browser":
                #     view_fn(timeframe=timeframe, query_str=query, level=level)
                # elif label == "Root Cause Analysis":
                #     view_fn(spike_ts=spike_ts)
                # else:
                #     view_fn(timeframe=timeframe)
                view_fn(timeframe=timeframe)
            except Exception as e:
                console.print(f"\n[red]Error:[/red] {e}")
            press_enter()
