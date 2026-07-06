"""
Display utilities for Prometheus metrics — mirrors monitor/kafka/display_utils.py.

Provides score_color, score_bar, status_icon, and fmt_score functions
bound to the Prometheus THRESHOLDS and INVERTED sets.
"""

from monitor.prometheus.collectors import THRESHOLDS, INVERTED, METRIC_META, GROUP_COLORS


def score_color(score, key: str) -> str:
    """Return 'green', 'yellow', 'red', or 'dim' based on thresholds."""
    if score is None:
        return "dim"
    warn, crit = THRESHOLDS.get(key, (50, 75))
    # Informational metrics (warn=0, crit=0) are always dim
    if warn == 0 and crit == 0:
        return "dim"
    if key in INVERTED:
        return "green" if score >= warn else "yellow" if score >= crit else "red"
    return "green" if score <= warn else "yellow" if score <= crit else "red"


def score_bar(score, width: int = 20) -> str:
    """Return a block-bar representation of a 0-100 score."""
    if score is None:
        return "─" * width
    filled = max(0, min(int((score / 100.0) * width), width))
    return "█" * filled + "░" * (width - filled)


def status_icon(score, key: str) -> str:
    """Return a colored circle icon based on the score threshold zone."""
    icons = {"green": "🟢", "yellow": "🟡", "red": "🔴", "dim": "⚪"}
    return icons.get(score_color(score, key), "⚪")


def fmt_score(score) -> str:
    """Format a score as a string, returning 'N/A' for None."""
    return f"{float(score):.1f}" if score is not None else "N/A"
