"""Library replication responses for the mesh (issue #410).

Pure builders turn the indexer's generation, changelog and snapshot into the
``/mesh/library/*`` wire payloads of docs/MESH_SEARCH.md section 2. Only shared
folders are served and only relative paths ever leave the node.
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # the sqlite indexer is only needed once a library is shared (#463)
    import library_index_v2

MAX_PAGE = 5000
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_STRING = 512
WIRE_FIELDS = ("content_key", "kind", "title", "sort_title", "year", "show", "season", "episode",
               "artist", "album_artist", "album", "disc", "track", "genre", "duration",
               "width", "height", "langs", "size")


def to_wire(entry: dict, label: str) -> dict:
    """Public shape of an entry: no absolute paths, no inode, no mtime."""
    wire = {key: entry.get(key) for key in WIRE_FIELDS}
    wire["folder_label"] = label
    wire["rel_path"] = entry.get("rel_path")
    return wire


def validate_entry(value: object) -> bool:
    """Schema-lite check used when applying a peer's pages (S5)."""
    if not isinstance(value, dict):
        return False
    for key in ("content_key", "kind", "title"):
        if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > MAX_STRING:
            return False
    for key, item in value.items():
        if isinstance(item, str) and len(item) > MAX_STRING:
            return False
        if isinstance(item, (dict, list)):
            return False
    return True


class RateLimiter:
    """Token bucket per peer; injectable clock."""

    def __init__(self, rate: float = 10.0, burst: int = 20,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self.clock = rate, burst, clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, peer: str) -> float:
        """0.0 when allowed, else seconds to wait (the Retry-After value)."""
        now = self.clock()
        with self._lock:
            tokens, stamp = self._buckets.get(peer, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - stamp) * self.rate)
            if tokens >= 1.0:
                self._buckets[peer] = (tokens - 1.0, now)
                if len(self._buckets) > 512:
                    for old in list(self._buckets)[:64]:
                        self._buckets.pop(old, None)
                return 0.0
            self._buckets[peer] = (tokens, now)
            return (1.0 - tokens) / self.rate


def build_generation(indexer: library_index_v2.LibraryIndexer) -> tuple[int, dict]:
    origin, epoch, seq = indexer.generation()
    return 200, {"origin": origin, "epoch": epoch, "seq": seq, "count": indexer.count(),
                 "caps": ["search.v1"]}


def _clamp(limit: object) -> int:
    try:
        return max(1, min(int(limit), MAX_PAGE))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return MAX_PAGE


def build_changes_response(indexer: library_index_v2.LibraryIndexer, epoch: object,
                           since: object, limit: object = MAX_PAGE) -> tuple[int, dict]:
    import library_index_v2
    try:
        start = int(since)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 400, {"error": "since must be an integer"}
    size = _clamp(limit)
    try:
        rows = indexer.changes_since(str(epoch), start, size)
    except library_index_v2.StaleGeneration:
        _o, current, _s = indexer.generation()
        return 410, {"error": "stale", "epoch": current}
    changes = []
    for row in rows:
        if row["op"] == "upsert":
            entry = row.get("entry")
            if not entry or not indexer._is_shared(entry["folder_id"]):
                continue  # superseded by a later row, or no longer shared
            changes.append({"seq": row["seq"], "op": "upsert",
                            "entry": to_wire(entry, indexer.folder_label(entry["folder_id"]))})
        else:
            changes.append({"seq": row["seq"], "op": "delete", "content_key": row["content_key"]})
    _o, current, newest = indexer.generation()
    last = rows[-1]["seq"] if rows else start
    return 200, {"epoch": current, "from": start, "to": last, "changes": changes,
                 "more": bool(rows) and len(rows) >= size and last < newest}


def build_snapshot_response(indexer: library_index_v2.LibraryIndexer, cursor: object,
                            limit: object = MAX_PAGE) -> tuple[int, dict]:
    items, nxt, (_origin, epoch, seq) = indexer.snapshot_page(
        str(cursor) if cursor else None, _clamp(limit), shared_only=True)
    return 200, {"epoch": epoch, "at_seq": seq, "next": nxt,
                 "entries": [to_wire(i, indexer.folder_label(i["folder_id"])) for i in items]}


def encode(payload: dict, accept_gzip: bool) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if accept_gzip:
        return gzip.compress(body, 5), {"Content-Encoding": "gzip"}
    return body, {}


class Replication:
    """Routing + limits for the three GET endpoints (used by the HTTP layer)."""

    def __init__(self, indexer: library_index_v2.LibraryIndexer,
                 limiter: RateLimiter | None = None) -> None:
        self.indexer = indexer
        self.limiter = limiter or RateLimiter()
        self._snapshots = threading.BoundedSemaphore(2)

    def handle(self, path: str, params: dict[str, str], peer: str
               ) -> tuple[int, dict, dict[str, str]]:
        wait = self.limiter.allow(peer)
        if wait:
            return 429, {"error": "slow down"}, {"Retry-After": str(max(1, int(wait + 0.999)))}
        if path == "/mesh/library/generation":
            status, payload = build_generation(self.indexer)
        elif path == "/mesh/library/changes":
            status, payload = build_changes_response(
                self.indexer, params.get("epoch", ""), params.get("since", ""),
                params.get("limit", MAX_PAGE))
        elif path == "/mesh/library/snapshot":
            if not self._snapshots.acquire(blocking=False):
                return 429, {"error": "busy"}, {"Retry-After": "1"}
            try:
                status, payload = build_snapshot_response(
                    self.indexer, params.get("cursor"), params.get("limit", MAX_PAGE))
            finally:
                self._snapshots.release()
        elif path == "/mesh/library/search":
            rows = self.indexer.search_rows(params.get("q", ""), _clamp(params.get("limit", 50)))
            status, payload = 200, {"entries": [to_wire(
                {**r, "rel_path": ""}, self.indexer.folder_label(r["folder_id"])) for r in rows]}
        else:
            return 404, {"error": "not found"}, {}
        return status, payload, {}
