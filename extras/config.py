import os

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()


# ── Env helpers ──────────────────────────────────────────────────

def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _choice(name: str, default: str, allowed: set[str]) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    return normalized if normalized in allowed else default


# ── OpenSearch ───────────────────────────────────────────────────

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = _int("OPENSEARCH_PORT", 9200)
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = os.getenv("OPENSEARCH_PASS", "admin")
OPENSEARCH_SSL = _bool("OPENSEARCH_SSL", False)
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "system-logs-*")

# ── Prometheus ───────────────────────────────────────────────────

PROMETHEUS_HOST = os.getenv("PROMETHEUS_HOST", OPENSEARCH_HOST)
PROMETHEUS_PORT = _int("PROMETHEUS_PORT", 9090)
PROMETHEUS_SCHEME = os.getenv("PROMETHEUS_SCHEME", "http")
PROMETHEUS_TIMEOUT = _int("PROMETHEUS_TIMEOUT_SECONDS", 6)

# ── Performance Analyzer ────────────────────────────────────────

PA_HOST = os.getenv("PA_HOST", OPENSEARCH_HOST)
PA_PORT = _int("PA_PORT", 9600)
PA_SCHEME = os.getenv("PA_SCHEME", "http")
PA_TIMEOUT = _int("PA_TIMEOUT_SECONDS", 4)

# ── Poller ───────────────────────────────────────────────────────

POLLER_DATA_DIR = os.getenv("POLLER_DATA_DIR", "poller/data")
HISTORY_SOURCE = _choice("HISTORICAL_METRICS_SOURCE", "auto", {"auto", "poller", "prometheus"})

# ── Thresholds ───────────────────────────────────────────────────

CPU_WARN, CPU_CRIT = 70, 90
HEAP_WARN, HEAP_CRIT = 75, 90
MEM_WARN, MEM_CRIT = 85, 95
DISK_WARN, DISK_CRIT = 80, 90

# ── Log display ──────────────────────────────────────────────────

LOG_COLORS = {
    "error": "red",
    "critical": "bold red",
    "warn": "yellow",
    "warning": "yellow",
    "info": "cyan",
    "debug": "dim",
}

KEYWORD_TAGS = {
    "CPU": ["cpu", "merge", "aggregat", "lucene"],
    "HEAP": ["heap", "memory", "outofmemory", "oom"],
    "GC": ["gc", "garbage", "pause", "overhead"],
    "DISK": ["disk", "watermark", "flood", "space", "read-only", "readonly"],
    "THREAD": ["rejected", "queue", "bulk", "thread pool"],
    "SEARCH": ["timeout", "slowlog", "slow", "circuit"],
}

ROOT_CAUSE_PATTERNS = [
    ("OutOfMemoryError", "🔴 JVM OOM — heap exhausted"),
    ("GC overhead limit", "🟠 GC overhead — excessive garbage collection"),
    ("disk usage exceeded", "🔴 Disk full / watermark breached"),
    ("circuit_breaking_exception", "🟠 Circuit breaker tripped — memory pressure"),
    ("flood stage", "🔴 Disk flood-stage — index set read-only"),
    ("high disk watermark", "🟡 High disk watermark crossed"),
    ("rejected execution", "🟠 Thread pool rejection — queue full"),
    ("bulk rejected", "🟠 Bulk indexing rejected — backpressure"),
    ("timeout", "🟡 Operation timeout"),
    ("failed to obtain", "🟡 Lock/resource contention"),
    ("connection refused", "🟡 Downstream connection refused"),
    ("shard failed", "🔴 Shard failure"),
    ("unassigned", "🟡 Unassigned shards detected"),
    ("slowlog", "🟡 Slow query/index detected"),
]

# ── Shared console ───────────────────────────────────────────────

console = Console()
