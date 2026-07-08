from rich.table import Table
from rich import box
from simple_term_menu import TerminalMenu

from archive.extras.config import console
from archive.extras.client import indices, shards
from archive.extras.utils import format_bytes, parse_size_string


def display_index_deep_dive(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Index Deep Dive[/bold cyan]")
    console.print()

    idx_list = indices()
    if not idx_list:
        console.print("[yellow]No indices found.[/yellow]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan",
                  title="[bold]All Indices (sorted by size)[/bold]", title_style="bold white", expand=True)
    table.add_column("#", style="dim", width=5, justify="right")
    table.add_column("Index Name", style="white", ratio=2)
    table.add_column("Size", style="yellow", width=14, justify="right")
    table.add_column("Documents", style="cyan", width=16, justify="right")
    table.add_column("Health", width=10, justify="center")
    table.add_column("Shards", width=10, justify="right")
    table.add_column("Replicas", width=10, justify="right")

    names = []
    for i, idx in enumerate(idx_list, 1):
        name = idx.get("index", "—")
        names.append(name)
        size = format_bytes(parse_size_string(idx.get("store.size", "0")))
        docs = idx.get("docs.count", "0")
        try:
            docs = f"{int(docs):,}"
        except (ValueError, TypeError):
            docs = str(docs)
        health = idx.get("health", "—")
        hc = {"green": "green", "yellow": "yellow", "red": "red"}.get(health.lower(), "white")
        table.add_row(str(i), name, size, docs, f"[{hc}]{health.upper()}[/{hc}]",
                      str(idx.get("pri", "—")), str(idx.get("rep", "—")))

    console.print(table)
    console.print()
    console.print("[dim]Select an index to inspect its shard layout:[/dim]")
    console.print()

    menu = TerminalMenu(names + ["Back"], menu_cursor="❯ ",
                        menu_cursor_style=("fg_cyan", "bold"), menu_highlight_style=("fg_cyan", "bold"))
    choice = menu.show()
    if choice is None or choice == len(names):
        return
    _show_shards(names[choice])


def _show_shards(index_name: str):
    console.print()
    console.rule(f"[bold cyan]Shard Layout — {index_name}[/bold cyan]")
    console.print()

    shard_list = shards(index=index_name)
    if not shard_list:
        console.print(f"[yellow]No shard data found for '{index_name}'.[/yellow]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Shard", style="white", width=8, justify="center")
    table.add_column("Type", style="dim", width=10, justify="center")
    table.add_column("State", width=14, justify="center")
    table.add_column("Node", style="yellow", ratio=1)
    table.add_column("Size", style="cyan", width=14, justify="right")
    table.add_column("Docs", style="white", width=14, justify="right")

    for s in shard_list:
        state = s.get("state", "—").upper()
        sc = {"STARTED": "green", "UNASSIGNED": "red", "RELOCATING": "yellow", "INITIALIZING": "yellow"}.get(state, "white")
        node = s.get("node") or "[red]unassigned[/red]"
        if node in (None, "null"):
            node = "[red]unassigned[/red]"
        size = format_bytes(parse_size_string(s.get("store", "0") or "0"))
        docs = s.get("docs", "0") or "0"
        try:
            docs = f"{int(docs):,}"
        except (ValueError, TypeError):
            docs = str(docs)
        table.add_row(
            str(s.get("shard", "—")),
            "Primary" if s.get("prirep", "") == "p" else "Replica",
            f"[{sc}]{state}[/{sc}]", node, size, docs,
        )

    console.print(table)
    console.print()
