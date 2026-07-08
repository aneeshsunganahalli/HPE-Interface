from rich.panel import Panel
from rich.table import Table
from rich import box

from archive.extras.config import console
from archive.extras.client import shards
from archive.extras.utils import format_bytes, parse_size_string


def display_shard_overview(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Shard Overview[/bold cyan]")
    console.print()

    all_shards = shards()
    if not all_shards:
        console.print("[yellow]No shard data found.[/yellow]")
        return

    groups: dict[str, list] = {"STARTED": [], "RELOCATING": [], "INITIALIZING": [], "UNASSIGNED": []}
    for s in all_shards:
        state = s.get("state", "UNKNOWN").upper()
        if state in groups:
            groups[state].append(s)

    # Summary
    parts = []
    for state, items in groups.items():
        count = len(items)
        if state == "UNASSIGNED" and count > 0:
            parts.append(f"[red]{state}: {count}[/red]")
        elif state == "STARTED":
            parts.append(f"[green]{state}: {count}[/green]")
        elif count > 0:
            parts.append(f"[yellow]{state}: {count}[/yellow]")
        else:
            parts.append(f"[dim]{state}: {count}[/dim]")

    console.print(Panel("  " + "    ".join(parts),
                        title="[bold]Shard State Summary[/bold]", title_align="left",
                        border_style="cyan", expand=False))
    console.print()

    # Per-group tables
    for state in ("STARTED", "RELOCATING", "INITIALIZING", "UNASSIGNED"):
        items = groups[state]
        if not items:
            continue

        is_bad = state == "UNASSIGNED"
        border = "red" if is_bad else "cyan"
        header = "bold red" if is_bad else "bold cyan"

        table = Table(box=box.ROUNDED, show_header=True, header_style=header,
                      title=f"[bold]{state}[/bold] ({len(items)} shards)",
                      title_style="bold red" if is_bad else "bold white",
                      expand=True, border_style=border if is_bad else None)
        table.add_column("Index", style="red" if is_bad else "white", ratio=2)
        table.add_column("Shard", width=8, justify="center")
        table.add_column("Type", width=10, justify="center")
        table.add_column("Node", style="yellow", ratio=1)
        table.add_column("Size", width=14, justify="right")
        table.add_column("Docs", width=14, justify="right")

        for s in items:
            node = s.get("node") or "[red]unassigned[/red]"
            if node in (None, "null"):
                node = "[red]unassigned[/red]"
            size = format_bytes(parse_size_string(s.get("store") or "0"))
            docs = s.get("docs") or "0"
            try:
                docs = f"{int(docs):,}"
            except (ValueError, TypeError):
                docs = str(docs)
            table.add_row(
                s.get("index", "—"), str(s.get("shard", "—")),
                "Primary" if s.get("prirep", "") == "p" else "Replica",
                node, size, docs,
            )

        console.print(table)
        console.print()

    unassigned = len(groups["UNASSIGNED"])
    if unassigned > 0:
        console.print(Panel(
            f"[red]{unassigned} unassigned shard(s) detected[/red] — this may affect data\n"
            "redundancy. Check that all nodes are online and have sufficient disk space.",
            title="[bold red]Attention[/bold red]", title_align="left",
            border_style="red", expand=False,
        ))
    else:
        console.print("  [green]✓  All shards are properly assigned.[/green]")
    console.print()
