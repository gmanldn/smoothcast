"""Play/queue a search result by content_key (#414). Pure decision logic; the probe is injected.

``MeshItem`` carries ``content_key`` + origin candidates and never a filesystem path. ``resolve`` tries
the local copy first, then online origins best-first, asking each to revalidate (300 ms budget supplied by
the probe); a 404/409/timeout falls through to the next origin. ``Commands`` makes enqueue idempotent per
``queue_command_id`` and rejects stale ``queue_revision``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

UNAVAILABLE = "This isn't available right now — its computer may be asleep."
PROBE_TIMEOUT_S, NEG_CACHE_S, MAX_ORIGINS = 0.3, 30.0, 8
_KEY = re.compile(r"[A-Za-z0-9:_\-]{6,128}\Z")
_PATHY = re.compile(r"(^/|^[A-Za-z]:\\|\\\\|\.\./|/home/|/Users/)")


@dataclass
class MeshItem:
    content_key: str
    title: str = ""
    duration: float | None = None
    origins: list[dict] = field(default_factory=list)   # {id, online, local?, rtt?, wired?}

    def public(self) -> dict:
        """What a client may see: no paths, no origin addresses."""
        return {"content_key": self.content_key, "title": self.title[:200], "duration": self.duration,
                "origins": [{"id": o["id"], "online": bool(o.get("online"))} for o in self.origins]}


def valid_key(key) -> bool:
    return isinstance(key, str) and bool(_KEY.match(key)) and not _PATHY.search(key)


def make_item(key: str, title: str, duration, origins: list[dict]) -> MeshItem | None:
    if not valid_key(key):
        return None
    clean = [{"id": str(o["id"])[:60], "online": bool(o.get("online")), "local": bool(o.get("local")), "rtt": float(o.get("rtt") or 0.0),
              "wired": bool(o.get("wired"))} for o in origins[:MAX_ORIGINS] if isinstance(o, dict) and o.get("id") and not _PATHY.search(str(o["id"]))]
    return MeshItem(key, str(title or "")[:200], duration if isinstance(duration, (int, float)) and duration >= 0 else None, clean)


def order(origins: list[dict]) -> list[dict]:
    """Local first, then online by wired, then lowest RTT, then id (stable)."""
    live = [o for o in origins if o.get("local") or o.get("online")]
    return sorted(live, key=lambda o: (not o.get("local"), not o.get("wired"), o.get("rtt", 0.0), o["id"]))


class Resolver:
    def __init__(self, clock) -> None:
        self.clock, self.bad = clock, {}                 # (origin, key) -> until

    def resolve(self, item: MeshItem, probe) -> dict:
        """probe(origin_id, key) -> (status, body). -> {ok, origin, size, tried[], error?}"""
        tried = []
        for o in order(item.origins):
            if o.get("local"):
                return {"ok": True, "origin": o["id"], "local": True, "size": None, "tried": tried}
            if self.bad.get((o["id"], item.content_key), 0) > self.clock():
                tried.append({"origin": o["id"], "why": "recently_failed"})
                continue
            try:
                status, body = probe(o["id"], item.content_key)
            except Exception:                            # a probe must never take playback down  # noqa: BLE001 - a probe must never take playback down
                status, body = 599, {}
            if status == 200 and isinstance(body, dict) and body.get("ok"):
                return {"ok": True, "origin": o["id"], "local": False, "size": body.get("size"), "tried": tried}
            why = {404: "gone", 409: "changed", 599: "error"}.get(status, "timeout" if status in (0, 408, 504) else f"http_{status}")
            tried.append({"origin": o["id"], "why": why})
            self.bad[(o["id"], item.content_key)] = self.clock() + NEG_CACHE_S
        return {"ok": False, "error": UNAVAILABLE, "tried": tried}


class Commands:
    """Idempotent, revision-checked enqueue by key."""

    def __init__(self) -> None:
        self.revision, self.queue, self.done = 0, [], {}

    def enqueue(self, command_id: str, revision: int, item: MeshItem | None) -> dict:
        if command_id in self.done:
            return {**self.done[command_id], "duplicate": True}
        if item is None:
            return {"ok": False, "error": "That item isn't valid."}
        if revision != self.revision:
            return {"ok": False, "error": "The queue changed — refresh and try again.", "revision": self.revision, "stale": True}
        self.queue.append(item)
        self.revision += 1
        res = {"ok": True, "revision": self.revision, "position": len(self.queue) - 1}
        self.done[command_id] = res
        if len(self.done) > 500:
            self.done.pop(next(iter(self.done)))
        return res

    def client_view(self) -> dict:
        return {"revision": self.revision, "items": [i.public() for i in self.queue]}
