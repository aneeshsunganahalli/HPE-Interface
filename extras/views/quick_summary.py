import datetime

from rich.panel import Panel

from extras.config import console, CPU_WARN, CPU_CRIT, HEAP_WARN, HEAP_CRIT, DISK_WARN, DISK_CRIT
from extras.client import cluster_health, cluster_stats, node_stats, disk_allocation, indices, shards
from extras.utils import format_bytes, parse_size_string, status_symbol, cluster_status_symbol, cluster_status_styled


def display_quick_summary(timeframe: str = "1h"):
    now = datetime.datetime.now().strftime("%H:%M")
    console.print()
    console.rule(f"[bold cyan]OpenSearch — Quick Summary[/bold cyan]  [dim](as of {now})[/dim]")
    console.print()

    warnings = []

    # ── Cluster Health ───────────────────────────────────────────
    health = cluster_health()
    if health:
        status = health.get("status", "unknown")
        num_nodes = health.get("number_of_nodes", 0)
        console.print(Panel(
            f"  Status  : {cluster_status_styled(status)} {cluster_status_symbol(status)}\n"
            f"  Nodes   : {num_nodes} active",
            title="[bold]Cluster Health[/bold]", title_align="left",
            border_style="cyan", expand=False,
        ))
        if status.lower() == "yellow":
            warnings.append("[yellow]⚠[/yellow]  Cluster is YELLOW — some replica shards are missing.")
        elif status.lower() == "red":
            warnings.append("[red]✗[/red]  Cluster is RED — some primary shards are unassigned.")
    else:
        console.print("[red]Could not retrieve cluster health.[/red]")

    # ── Resources ────────────────────────────────────────────────
    cs = cluster_stats()
    ns = node_stats()
    da = disk_allocation()

    heap_used = heap_max = mem_used = mem_total = disk_used = disk_total = 0
    if cs:
        nodes_data = cs.get("nodes", {})
        os_mem = nodes_data.get("os", {}).get("mem", {})
        mem_used = os_mem.get("used_in_bytes", 0)
        mem_total = os_mem.get("total_in_bytes", 0)
        jvm = nodes_data.get("jvm", {}).get("mem", {})
        heap_used = jvm.get("heap_used_in_bytes", 0)
        heap_max = jvm.get("heap_max_in_bytes", 0)
        fs = nodes_data.get("fs", {})
        fs_total = fs.get("total_in_bytes", 0)
        fs_avail = fs.get("available_in_bytes", 0)
        disk_used = fs_total - fs_avail
        disk_total = fs_total

    # Per-node CPU and heap for warnings
    node_cpus, node_heaps = [], []
    if ns and "nodes" in ns:
        for nid, n in ns["nodes"].items():
            name = n.get("name", nid[:8])
            cpu = n.get("os", {}).get("cpu", {}).get("percent", 0)
            node_cpus.append((name, cpu))
            jvm_m = n.get("jvm", {}).get("mem", {})
            hu, hm = jvm_m.get("heap_used_in_bytes", 0), jvm_m.get("heap_max_in_bytes", 0)
            if hm > 0:
                node_heaps.append((name, hu / hm * 100))

    avg_cpu = sum(c for _, c in node_cpus) / len(node_cpus) if node_cpus else 0

    node_disks = []
    if da:
        for entry in da:
            name = entry.get("node", "unknown")
            du = parse_size_string(entry.get("disk.used", "0"))
            dt = parse_size_string(entry.get("disk.total", "0"))
            if dt > 0:
                node_disks.append((name, du / dt * 100))

    heap_pct = (heap_used / heap_max * 100) if heap_max > 0 else 0
    disk_pct = (disk_used / disk_total * 100) if disk_total > 0 else 0

    console.print(Panel(
        f"  CPU        : {avg_cpu:.0f}%                       {status_symbol(avg_cpu, CPU_WARN, CPU_CRIT)}\n"
        f"  JVM Heap   : {format_bytes(heap_used)} / {format_bytes(heap_max)}   {status_symbol(heap_pct, HEAP_WARN, HEAP_CRIT)}\n"
        f"  System RAM : {format_bytes(mem_used)} / {format_bytes(mem_total)}"
        f"   [dim](normal — OS uses RAM as cache)[/dim]\n"
        f"  Disk       : {format_bytes(disk_used)} / {format_bytes(disk_total)} {status_symbol(disk_pct, DISK_WARN, DISK_CRIT)}",
        title="[bold]Resources (cluster-wide)[/bold]", title_align="left",
        border_style="cyan", expand=False,
    ))

    # Per-node warnings
    for name, cpu in node_cpus:
        if cpu >= CPU_CRIT:
            warnings.append(f"[red]✗[/red]  CPU at {cpu}% on {name} — critically high.")
        elif cpu >= CPU_WARN:
            warnings.append(f"[yellow]⚠[/yellow]  CPU at {cpu}% on {name} — consider checking running tasks.")

    for name, hp in node_heaps:
        if hp >= HEAP_CRIT:
            warnings.append(f"[red]✗[/red]  JVM Heap at {hp:.0f}% on {name} — risk of OutOfMemory.")
        elif hp >= HEAP_WARN:
            warnings.append(f"[yellow]⚠[/yellow]  JVM Heap at {hp:.0f}% on {name} — consider reducing load.")

    for name, dp in node_disks:
        if dp >= DISK_CRIT:
            warnings.append(f"[red]✗[/red]  Disk at {dp:.0f}% on {name} — critically full.")
        elif dp >= DISK_WARN:
            warnings.append(f"[yellow]⚠[/yellow]  Disk at {dp:.0f}% on {name} — clean old indices soon.")

    # ── Index Activity ───────────────────────────────────────────
    idx_list = indices()
    cs_idx = cs.get("indices", {}) if cs else {}
    total_docs = cs_idx.get("docs", {}).get("count", 0)
    idx_ops = cs_idx.get("indexing", {}).get("index_total", 0)
    query_ops = cs_idx.get("search", {}).get("query_total", 0)

    if idx_list:
        total_data = sum(parse_size_string(i.get("store.size", "0")) for i in idx_list)
        largest = idx_list[0]
        console.print(Panel(
            f"  Total indices  : {len(idx_list)}\n"
            f"  Total documents: {total_docs:,}\n"
            f"  Total data     : {format_bytes(total_data)}\n"
            f"  Indexing ops   : {idx_ops:,}  [dim](cumulative)[/dim]\n"
            f"  Search queries : {query_ops:,}  [dim](cumulative)[/dim]\n"
            f"  Largest index  : {largest.get('index', '—')} ({format_bytes(parse_size_string(largest.get('store.size', '0')))})",
            title="[bold]Index Activity[/bold]", title_align="left",
            border_style="cyan", expand=False,
        ))
    else:
        console.print(Panel("  No index data available.",
                            title="[bold]Index Activity[/bold]", title_align="left",
                            border_style="cyan", expand=False))

    # ── Shards ───────────────────────────────────────────────────
    all_shards = shards()
    if all_shards:
        active = sum(1 for s in all_shards if s.get("state", "").upper() == "STARTED")
        unassigned = sum(1 for s in all_shards if s.get("state", "").upper() == "UNASSIGNED")
        relocating = sum(1 for s in all_shards if s.get("state", "").upper() == "RELOCATING")
        initializing = sum(1 for s in all_shards if s.get("state", "").upper() == "INITIALIZING")

        text = f"  Active     : {active}\n"
        if relocating:
            text += f"  Relocating : {relocating}\n"
        if initializing:
            text += f"  Initializing: {initializing}\n"
        sym = "[green]✓[/green]" if unassigned == 0 else "[red]✗[/red]"
        text += f"  Unassigned : {unassigned}  {sym}"

        console.print(Panel(text, title="[bold]Shards[/bold]", title_align="left",
                            border_style="cyan", expand=False))
        if unassigned > 0:
            warnings.append(f"[red]✗[/red]  {unassigned} unassigned shard(s) detected.")
    else:
        console.print(Panel("  No shard data available.",
                            title="[bold]Shards[/bold]", title_align="left",
                            border_style="cyan", expand=False))

    # ── Warnings ─────────────────────────────────────────────────
    if warnings:
        console.print()
        console.rule("[bold yellow]Alerts[/bold yellow]")
        for w in warnings:
            console.print(f"  {w}")
    else:
        console.print()
        console.print("  [green]✓  All systems healthy — no issues detected.[/green]")
    console.print()
