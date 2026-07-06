from __future__ import annotations

import urllib3
from opensearchpy import OpenSearch

from extras.config import (
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASS,
    OPENSEARCH_SSL, OPENSEARCH_INDEX, console,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_client: OpenSearch | None = None


def _get_client() -> OpenSearch:
    global _client
    if _client is None:
        scheme = "https" if OPENSEARCH_SSL else "http"
        _client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
            use_ssl=OPENSEARCH_SSL,
            verify_certs=False,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            scheme=scheme,
            timeout=30,
            max_retries=2,
            retry_on_timeout=True,
        )
    return _client


def _safe(fn, fallback=None):
    try:
        return fn()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return fallback if fallback is not None else ({} if callable(fallback) else fallback)


# ── Cluster APIs ─────────────────────────────────────────────────

def cluster_health() -> dict:
    try:
        return _get_client().cluster.health()
    except Exception as e:
        console.print(f"[red]Error fetching cluster health:[/red] {e}")
        return {}


def cluster_stats() -> dict:
    try:
        return _get_client().cluster.stats()
    except Exception as e:
        console.print(f"[red]Error fetching cluster stats:[/red] {e}")
        return {}


def node_stats() -> dict:
    try:
        return _get_client().nodes.stats(metric="os,jvm,fs,indices")
    except Exception as e:
        console.print(f"[red]Error fetching node stats:[/red] {e}")
        return {}


# ── Cat APIs ─────────────────────────────────────────────────────

def disk_allocation() -> list:
    try:
        return _get_client().cat.allocation(format="json", v=True)
    except Exception as e:
        console.print(f"[red]Error fetching disk allocation:[/red] {e}")
        return []


def indices() -> list:
    try:
        return _get_client().cat.indices(format="json", v=True, s="store.size:desc")
    except Exception as e:
        console.print(f"[red]Error fetching indices:[/red] {e}")
        return []


def shards(index: str = None) -> list:
    try:
        c = _get_client()
        if index:
            return c.cat.shards(index=index, format="json", v=True)
        return c.cat.shards(format="json", v=True)
    except Exception as e:
        console.print(f"[red]Error fetching shards:[/red] {e}")
        return []


def data_streams() -> dict:
    try:
        return _get_client().indices.get_data_stream()
    except Exception as e:
        console.print(f"[red]Error fetching data streams:[/red] {e}")
        return {}


# ── Log search APIs ──────────────────────────────────────────────

def search_logs(query_str: str = "*", minutes: int = 30, size: int = 20, level: str = None) -> list:
    must = [
        {"query_string": {"query": query_str, "analyze_wildcard": False}},
        {"range": {"@timestamp": {"gte": f"now-{minutes}m", "lte": "now"}}},
    ]
    if level:
        must.append({"match": {"log.level": level.lower()}})

    body = {
        "size": size,
        "timeout": "20s",
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {"bool": {"must": must}},
        "_source": ["@timestamp", "message", "log.level", "hostname", "instance", "program"],
    }
    try:
        return _get_client().search(index=OPENSEARCH_INDEX, body=body)["hits"]["hits"]
    except Exception as e:
        console.print(f"[red]Error searching logs:[/red] {e}")
        return []


def error_summary(minutes: int = 60) -> list:
    body = {
        "size": 0,
        "timeout": "20s",
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": f"now-{minutes}m", "lte": "now"}}},
                    {"terms": {"log.level": ["error", "warn", "warning", "critical"]}},
                ]
            }
        },
        "aggs": {
            "by_host": {
                "terms": {"field": "hostname.keyword", "size": 10},
                "aggs": {"by_level": {"terms": {"field": "log.level.keyword", "size": 5}}},
            }
        },
    }
    try:
        res = _get_client().search(index=OPENSEARCH_INDEX, body=body)
        return res.get("aggregations", {}).get("by_host", {}).get("buckets", [])
    except Exception as e:
        console.print(f"[red]Error fetching error summary:[/red] {e}")
        return []


def log_rate(minutes: int = 60, interval: str = "5m") -> list:
    body = {
        "size": 0,
        "timeout": "20s",
        "query": {"range": {"@timestamp": {"gte": f"now-{minutes}m", "lte": "now"}}},
        "aggs": {
            "over_time": {
                "date_histogram": {"field": "@timestamp", "fixed_interval": interval, "min_doc_count": 0},
                "aggs": {"by_level": {"terms": {"field": "log.level.keyword", "size": 5}}},
            }
        },
    }
    try:
        res = _get_client().search(index=OPENSEARCH_INDEX, body=body)
        return res.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    except Exception as e:
        console.print(f"[red]Error fetching log rate:[/red] {e}")
        return []


def logs_for_spike(start: str, end: str, size: int = 100) -> list:
    body = {
        "size": size,
        "timeout": "20s",
        "sort": [{"@timestamp": {"order": "asc"}}],
        "query": {"range": {"@timestamp": {"gte": start, "lte": end}}},
        "_source": ["@timestamp", "message", "log.level", "hostname", "program"],
    }
    try:
        return _get_client().search(index=OPENSEARCH_INDEX, body=body)["hits"]["hits"]
    except Exception as e:
        console.print(f"[red]Error fetching logs for spike:[/red] {e}")
        return []
