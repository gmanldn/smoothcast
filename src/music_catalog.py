"""Shared music catalogue view for paired guests (#349). Pure; no filesystem paths.

Entries come from the host's index restricted to *shared roots*. Guests get
opaque ids, bounded metadata and capped pages. ``entry_for_queue`` is the
revalidation step used right before queueing: it re-checks that the id is still
shared (revoke hides entries at once) and returns the host path only to the
host-side caller.
"""
from __future__ import annotations

import hashlib
import hmac

PAGE_MAX = 50
Q_MAX = 80


def media_id(secret: bytes, root: str, rel: str) -> str:
    return "m" + hmac.new(secret, f"{root}\0{rel}".encode(), hashlib.sha256).hexdigest()[:20]


class Catalog:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self._shared: set[str] = set()
        self._rows: dict[str, dict] = {}      # id -> row (host-side, includes root/rel)

    def share(self, root: str) -> None:
        self._shared.add(root)

    def revoke(self, root: str) -> None:
        self._shared.discard(root)

    def load(self, root: str, items: list[dict]) -> int:
        """Host-side ingest. Items: {rel,title,artist,album,track,disc,duration}. Unshared roots ignored."""
        if root not in self._shared:
            return 0
        n = 0
        for it in items:
            rel = str(it.get("rel") or "")
            if not rel or ".." in rel.split("/") or rel.startswith("/"):
                continue
            mid = media_id(self._secret, root, rel)
            self._rows[mid] = {"id": mid, "root": root, "rel": rel,
                               "title": str(it.get("title") or rel.rsplit("/", 1)[-1])[:120],
                               "artist": str(it.get("artist") or "")[:80], "album": str(it.get("album") or "")[:80],
                               "track": int(it.get("track") or 0), "disc": int(it.get("disc") or 1),
                               "duration": it.get("duration") if isinstance(it.get("duration"), (int, float)) else None}
            n += 1
        return n

    def _visible(self):
        return [r for r in self._rows.values() if r["root"] in self._shared]

    @staticmethod
    def _public(r: dict) -> dict:
        return {k: r[k] for k in ("id", "title", "artist", "album", "track", "disc", "duration")}

    def search(self, query: str = "", artist: str = "", album: str = "", offset: int = 0, limit: int = 25) -> dict:
        q = query.strip().lower()[:Q_MAX]
        limit = max(1, min(int(limit), PAGE_MAX))
        offset = max(0, int(offset))
        rows = [r for r in self._visible()
                if (not q or q in f"{r['title']} {r['artist']} {r['album']}".lower())
                and (not artist or r["artist"] == artist) and (not album or r["album"] == album)]
        rows.sort(key=lambda r: (r["artist"].lower(), r["album"].lower(), r["disc"], r["track"], r["title"].lower()))
        return {"total": len(rows), "offset": offset, "items": [self._public(r) for r in rows[offset:offset + limit]]}

    def albums(self) -> list[dict]:
        seen: dict[tuple, int] = {}
        for r in self._visible():
            seen[(r["artist"], r["album"])] = seen.get((r["artist"], r["album"]), 0) + 1
        return [{"artist": a, "album": b, "tracks": n} for (a, b), n in sorted(seen.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1].lower()))]

    def album_ids(self, artist: str, album: str) -> list[str]:
        rows = [r for r in self._visible() if r["artist"] == artist and r["album"] == album]
        rows.sort(key=lambda r: (r["disc"], r["track"], r["title"].lower()))
        return [r["id"] for r in rows][:200]

    def entry_for_queue(self, mid: str) -> dict | None:
        """Host-side only: the row (with root/rel) if still shared, else None."""
        r = self._rows.get(mid)
        return r if r and r["root"] in self._shared else None
