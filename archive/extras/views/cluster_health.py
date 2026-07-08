from rich.panel import Panel
from rich.table import Table
from rich import box

from archive.extras.config import console
from archive.extras.client import cluster_health
from archive.extras.utils import cluster_status_styled, cluster_status_symbol


def display_cluster_health(timeframe: str = "1h"):
    console.print()
    console.rule("[bold cyan]OpenSearch — Cluster Health[/bold cyan]")
    console.print()

    health = cluster_health()
    if not health:
        console.print("[red]Could not retrieve cluster health data.[/red]")
        return

    status = health.get("status", "unknown")
    console.print(Panel(
        f"  Cluster Status : {cluster_status_styled(status)} {cluster_status_symbol(status)}",
        border_style="cyan", expand=False,
    ))

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=False)
    table.add_column("Metric", style="white", width=28)
    table.add_column("Value", style="bold", width=20, justify="right")

    rows = [
        ("Total Nodes", health.get("number_of_nodes", 0)),
        ("Data Nodes", health.get("number_of_data_nodes", 0)),
        ("Active Primary Shards", health.get("active_primary_shards", 0)),
        ("Active Shards (total)", health.get("active_shards", 0)),
    ]
    for label, val in rows:
        table.add_row(label, str(val))

    for label, key, warn_color in [
        ("Relocating Shards", "relocating_shards", "yellow"),
        ("Initializing Shards", "initializing_shards", "yellow"),
        ("Unassigned Shards", "unassigned_shards", "red"),
        ("Pending Tasks", "number_of_pending_tasks", "yellow"),
    ]:
        val = health.get(key, 0)
        color = warn_color if val > 0 else "green"
        table.add_row(label, f"[{color}]{val}[/{color}]")

    console.print(table)
    console.print()

    explanations = {
        "green": (
            "[green]All primary and replica shards are assigned.[/green]\n"
            "Your cluster is fully operational with complete data redundancy.",
            "green",
        ),
        "yellow": (
            "[yellow]Some replica shards are not assigned to any node.[/yellow]\n"
            "Your data is still accessible, but redundancy is reduced.\n"
            "If a node goes down, you might lose copies of some data.",
            "yellow",
        ),
        "red": (
            "[red]Some primary shards are not assigned — data may be unavailable.[/red]\n"
            "Searches and writes to affected indices will fail.\n"
            "Common causes: node down, disk full, shard allocation disabled.",
            "red",
        ),
    }
    text, color = explanations.get(status.lower(), ("", "white"))
    if text:
        console.print(Panel(text, title=f"[bold {color}]What this means[/bold {color}]",
                            title_align="left", border_style=color, expand=False))
    console.print()
