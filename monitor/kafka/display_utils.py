from monitor.kafka.collectors import THRESHOLDS, INVERTED, METRIC_META, GROUP_COLORS

def score_color(score, key: str) -> str:
    if score is None:
        return "dim"
    warn, crit = THRESHOLDS.get(key, (50, 75))
    if key in INVERTED:
        return "green" if score >= warn else "yellow" if score >= crit else "red"
    return "green" if score <= warn else "yellow" if score <= crit else "red"

def score_bar(score, width: int = 20) -> str:
    if score is None:
        return "─" * width
    filled = max(0, min(int((score / 100.0) * width), width))
    return "█" * filled + "░" * (width - filled)

def status_icon(score, key: str) -> str:
    icons = {"green": "🟢", "yellow": "🟡", "red": "🔴", "dim": "⚪"}
    return icons.get(score_color(score, key), "⚪")

def fmt_score(score) -> str:
    return f"{float(score):.1f}" if score is not None else "N/A"