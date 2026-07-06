from __future__ import annotations

from poller.collectors.system import _classify_fd_entries


def test_classify_fd_entries_groups_common_targets():
    entries = ["0", "1", "2", "3", "4", "5"]

    def fake_readlink(path: str) -> str:
        suffix = path.rsplit("/", 1)[-1]
        mapping = {
            "0": "/var/log/opensearch/server.log",
            "1": "socket:[12345]",
            "2": "pipe:[67890]",
            "3": "anon_inode:[eventpoll]",
            "4": "memfd:some-buffer",
            "5": "unknown-target",
        }
        return mapping[suffix]

    original_readlink = __import__("os").readlink
    try:
        __import__("os").readlink = fake_readlink
        counts = _classify_fd_entries(4321, entries)
    finally:
        __import__("os").readlink = original_readlink

    assert counts == {
        "files": 1,
        "sockets": 1,
        "pipes": 1,
        "anon_inode": 1,
        "memfd": 1,
        "other": 1,
    }