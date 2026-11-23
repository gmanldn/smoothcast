"""House-wide search: local index + peer replicas + live fan-out (issue #412).

Cached results (local and replicas) are returned immediately; origins whose
replica is missing or past its soft TTL are asked live with a short deadline
and their late hits stream in. See docs/MESH_SEARCH.md section 4.
"""
from __future__ import annotations

import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from typing import Callable, Iterator

import search_engine

FANOUT_DEADLINE = 0.3
MAX_MERGE = 300


def _copy(origin: str, info: dict) -> dict:
    state = info.get("state", "stale")
    online = origin == "local" or state in ("fresh", "stale")
    copy = {"origin": origin, "origin_name": info.get("name", ""), "online": online}
    if not online and info.get("last_seen_at"):
        copy["last_seen"] = info["last_seen_at"]
    return copy


def merge(local_rows: list[dict], replica_rows: list[dict], origins: dict[str, dict]) -> list[dict]:
    """Dedupe by content_key, collect every copy, rank online results first."""
    merged: dict[str, dict] = {}
    rank = 0
    for origin, rows in (("local", local_rows), ("", replica_rows)):
        for row in rows:
            rank += 1
            source = origin or row.get("origin_id", "")
            info = {"name": "This computer", "state": "fresh"} if source == "local" else \
                origins.get(source, {"name": "", "state": "offline"})
            entry = merged.get(row["content_key"])
            if entry is None:
                entry = merged[row["content_key"]] = {**row, "copies": [], "_rank": rank}
            if all(c["origin"] != source for c in entry["copies"]):
                entry["copies"].append(_copy(source, info))
            entry["_rank"] = min(entry["_rank"], rank)
    out = []
    for entry in merged.values():
        entry["copies"].sort(key=lambda c: (not c["online"], c["origin"] != "local", c["origin"]))
        entry["_online"] = any(c["online"] for c in entry["copies"])
        out.append(entry)
    out.sort(key=lambda e: (not e["_online"], e["_rank"], e["sort_title"], e["content_key"]))
    for entry in out:
        entry.pop("_rank", None)
        entry.pop("_online", None)
    return out


class FederatedSearch:
    def __init__(self, local: Callable[[str, int], list[dict]],
                 replicas: Callable[[str, int], list[dict]],
                 origins: Callable[[], dict[str, dict]],
                 fetch: Callable[[str, str, dict], tuple[int, dict]], *,
                 clock: Callable[[], float] = time.monotonic,
                 deadline: float = FANOUT_DEADLINE) -> None:
        self.local, self.replicas, self.origins = local, replicas, origins
        self.fetch, self.clock, self.deadline = fetch, clock, deadline
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fanout")

    def close(self) -> None:
        """Stop the fan-out worker pool; pending live queries are dropped."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _targets(self, origins: dict[str, dict]) -> list[str]:
        return [oid for oid, info in origins.items()
                if info.get("state") != "offline"
                and (info.get("state") == "stale" or info.get("last_synced_at") is None)]

    def _cached(self, text: str, limit: int) -> tuple[list[dict], dict[str, dict]]:
        origins = self.origins()
        rows = merge(self.local(text, MAX_MERGE), self.replicas(text, MAX_MERGE), origins)
        return rows, origins

    def _ask(self, origin_id: str, text: str, limit: int) -> list[dict]:
        status, body = self.fetch(origin_id, "/mesh/library/search", {"q": text, "limit": limit})
        if status != 200 or not isinstance(body, dict):
            return []
        entries = body.get("entries")
        return [{**e, "origin_id": origin_id} for e in entries
                if isinstance(e, dict) and isinstance(e.get("content_key"), str)] \
            if isinstance(entries, list) else []

    def _page(self, rows: list[dict], limit: int, cursor: str | None, pending: list[str],
              partial: bool, text: str) -> dict:
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError, OverflowError):
            limit = 50
        # The cursor is an untrusted HTTP parameter. Reject negative indices,
        # noncanonical encodings, arbitrarily long integers and offsets beyond
        # the current result set; Python's negative slices repeat old items.
        offset = 0
        if isinstance(cursor, str) and 0 < len(cursor) <= 16:
            try:
                raw = base64.b64decode(cursor, altchars=b"-_", validate=True)
                if (0 < len(raw) <= 5 and raw.isascii() and raw.isdecimal()
                        and base64.urlsafe_b64encode(raw).decode() == cursor):
                    candidate = int(raw)
                    if candidate <= len(rows):
                        offset = candidate
            except (ValueError, UnicodeError, base64.binascii.Error):
                pass
        page = rows[offset:offset + limit]
        more = len(rows) > offset + limit
        nxt = base64.urlsafe_b64encode(str(offset + limit).encode()).decode() if more else None
        return {"q": text[:200], "partial": partial or bool(pending), "pending_origins": pending,
                "groups": search_engine.group(page), "next": nxt}

    def search(self, text: str, limit: int = 50, cursor: str | None = None) -> dict:
        """Cached results plus whatever fan-out answers inside the deadline."""
        rows, origins = self._cached(text, limit)
        targets = self._targets(origins)
        pending: list[str] = []
        if targets:
            futures = {self._pool.submit(self._ask, oid, text, limit): oid for oid in targets}
            done, not_done = wait(futures, timeout=self.deadline)
            extra: list[dict] = []
            for future in done:
                try:
                    extra += future.result()
                except Exception:
                    pass
            pending = [futures[f] for f in not_done]
            for future in not_done:
                future.cancel()
            if extra:
                rows = merge([r for r in rows if any(c["origin"] == "local" for c in r["copies"])],
                             [*self._flatten(rows), *extra], origins)
        return self._page(rows, limit, cursor, pending, False, text)

    @staticmethod
    def _flatten(rows: list[dict]) -> list[dict]:
        """Replica-side rows of merged results, one per remote copy."""
        out = []
        for row in rows:
            for copy in row["copies"]:
                if copy["origin"] != "local":
                    out.append({**{k: v for k, v in row.items() if k != "copies"},
                                "origin_id": copy["origin"]})
        return out

    def stream(self, text: str, limit: int = 50) -> Iterator[tuple[str, dict]]:
        """Yield ('results'|'more'|'done', payload): cached first, then late origins."""
        rows, origins = self._cached(text, limit)
        targets = self._targets(origins)
        yield "results", self._page(rows, limit, None, list(targets), False, text)
        if targets:
            futures = {self._pool.submit(self._ask, oid, text, limit): oid for oid in targets}
            end = self.clock() + max(self.deadline * 6, 1.5)
            remaining = dict(futures)
            while remaining and self.clock() < end:
                done, _ = wait(remaining, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in done:
                    oid = remaining.pop(future)
                    try:
                        extra = future.result()
                    except Exception:
                        extra = []
                    if extra:
                        rows = merge([r for r in rows if any(c["origin"] == "local" for c in r["copies"])],
                                     [*self._flatten(rows), *extra], origins)
                        yield "more", {**self._page(rows, limit, None, list(remaining.values()),
                                                    False, text), "origin": oid}
        yield "done", {"q": text[:200]}
