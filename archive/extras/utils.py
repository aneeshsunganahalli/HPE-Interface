import re

from rich.prompt import Prompt

from archive.extras.config import console


# ── Byte formatting ──────────────────────────────────────────────

def format_bytes(num_bytes: float) -> str:
    if num_bytes is None or num_bytes < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if num_bytes != int(num_bytes) else f"{int(num_bytes)} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} EB"


def parse_size_string(size_str: str) -> float:
    if not size_str:
        return 0.0
    size_str = size_str.strip().lower()
    multipliers = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, "pb": 1024**5}
    match = re.match(r"^([\d.]+)\s*([a-z]+)$", size_str)
    if not match:
        try:
            return float(size_str)
        except ValueError:
            return 0.0
    return float(match.group(1)) * multipliers.get(match.group(2), 1)


# ── Status indicators ───────────────────────────────────────────

def status_symbol(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "[red]✗[/red]"
    if value >= warn:
        return "[yellow]⚠[/yellow]"
    return "[green]✓[/green]"


def status_color(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "red"
    if value >= warn:
        return "yellow"
    return "green"


def cluster_status_symbol(status: str) -> str:
    s = status.lower()
    if s == "green":
        return "[green]✓[/green]"
    if s == "yellow":
        return "[yellow]⚠[/yellow]"
    return "[red]✗[/red]"


def cluster_status_styled(status: str) -> str:
    color = status.lower() if status.lower() in ("green", "yellow", "red") else "white"
    return f"[{color}]{status.upper()}[/{color}]"


# ── Timeframe helpers ────────────────────────────────────────────

def timeframe_to_minutes(tf: str) -> int:
    m = re.fullmatch(r"(\d+)([mhd])", tf.strip().lower())
    if not m:
        return 60
    n, unit = int(m.group(1)), m.group(2)
    return n * {"m": 1, "h": 60, "d": 1440}[unit]


def is_realtime(tf: str) -> bool:
    return tf.strip().lower() in {"real-time", "realtime"}


def timeframe_to_prom_range(tf: str) -> str:
    if is_realtime(tf):
        return "1h"
    m = re.fullmatch(r"(\d+)([mhd])", tf.strip().lower())
    if not m:
        return "1h"
    return f"{int(m.group(1))}{m.group(2)}"


# ── Interaction ──────────────────────────────────────────────────

def press_enter():
    console.print()
    Prompt.ask("[dim]Press Enter to return[/dim]", default="")
