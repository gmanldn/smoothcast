"""House vs solo room queues (#429). Pure, namespaced, revision-isolated.

Each room has ``queue_mode`` house|solo. Queue actions take ``queue: 'house'|<room_id>`` (default house).
Each namespace has its own revision, so editing a solo queue never touches the house revision. Rejoin
appends solo items to the house queue deduped by content_key; a deleted solo room folds in the same way.
"""
from __future__ import annotations

import re

HOUSE = "house"
MAX_ITEMS = 500
_ROOM = re.compile(r"[A-Za-z0-9_\-:.]{1,64}\Z")


def header(mode: str, room_name: str = "") -> str:
    return "House queue" if mode != "solo" else f"{(room_name or 'This room')[:40]} (solo)"


class RoomQueues:
    def __init__(self) -> None:
        self.q: dict[str, list[dict]] = {HOUSE: []}
        self.rev: dict[str, int] = {HOUSE: 0}
        self.mode: dict[str, str] = {}
        self.names: dict[str, str] = {}

    def resolve(self, queue) -> str | None:
        """Namespace for an action's ``queue`` field; unknown room -> None."""
        if queue in (None, "", HOUSE):
            return HOUSE
        return queue if isinstance(queue, str) and queue in self.q else None

    def active(self, room_id: str) -> str:
        """Which queue a controlling phone sees for this room."""
        return room_id if self.mode.get(room_id) == "solo" and room_id in self.q else HOUSE

    def view(self, room_id: str) -> dict:
        ns = self.active(room_id)
        return {"queue": ns, "header": header("solo" if ns != HOUSE else "house", self.names.get(room_id, "")), "revision": self.rev[ns],
                "items": [dict(i) for i in self.q[ns]]}

    def add(self, queue, item: dict, revision: int | None = None) -> dict:
        ns = self.resolve(queue)
        if ns is None:
            return {"ok": False, "error": "That room isn't available."}
        if revision is not None and revision != self.rev[ns]:
            return {"ok": False, "error": "The queue changed — refresh and try again.", "stale": True, "revision": self.rev[ns]}
        if len(self.q[ns]) >= MAX_ITEMS or not isinstance(item.get("content_key"), str):
            return {"ok": False, "error": "The queue is full." if len(self.q[ns]) >= MAX_ITEMS else "That item isn't valid."}
        self.q[ns].append(dict(item))
        self.rev[ns] += 1
        return {"ok": True, "queue": ns, "revision": self.rev[ns]}

    def remove(self, queue, content_key: str) -> dict:
        ns = self.resolve(queue)
        if ns is None:
            return {"ok": False, "error": "That room isn't available."}
        n = len(self.q[ns])
        self.q[ns] = [i for i in self.q[ns] if i.get("content_key") != content_key]
        if len(self.q[ns]) != n:
            self.rev[ns] += 1
        return {"ok": True, "queue": ns, "revision": self.rev[ns]}

    def go_solo(self, room_id: str, name: str = "", take_current=None) -> dict:
        if not isinstance(room_id, str) or not _ROOM.match(room_id) or room_id == HOUSE:
            return {"ok": False, "error": "That room isn't available."}
        self.mode[room_id], self.names[room_id] = "solo", name[:40]
        self.q.setdefault(room_id, [])
        self.rev.setdefault(room_id, 0)
        if take_current and isinstance(take_current, dict) and not self.q[room_id]:     # nothing copied unless asked
            self.q[room_id].append(dict(take_current))
            self.rev[room_id] += 1
        return {"ok": True, "queue": room_id, "revision": self.rev[room_id]}

    def rejoin(self, room_id: str, confirmed: bool) -> dict:
        """Append solo items to the house queue (dedupe by content_key) only after confirmation."""
        if self.mode.get(room_id) != "solo":
            return {"ok": True, "appended": 0}
        n = len(self.q.get(room_id, []))
        if not confirmed:
            return {"ok": False, "needs_confirmation": True, "message": f"Add {n} item{'s' if n != 1 else ''} to the House queue?"}
        return {"ok": True, **self._fold(room_id), "queue": HOUSE}

    def room_deleted(self, room_id: str) -> dict:
        return {"ok": True, **self._fold(room_id), "queue": HOUSE} if room_id in self.q and room_id != HOUSE else {"ok": True, "appended": 0}

    def _fold(self, room_id: str) -> dict:
        have = {i.get("content_key") for i in self.q[HOUSE]}
        add = []
        for i in self.q.get(room_id, []):
            if i.get("content_key") not in have and len(self.q[HOUSE]) + len(add) < MAX_ITEMS:
                have.add(i.get("content_key")); add.append(i)
        self.q[HOUSE] += add
        if add:
            self.rev[HOUSE] += 1
        for d in (self.q, self.rev, self.mode, self.names):
            d.pop(room_id, None)
        return {"appended": len(add), "revision": self.rev[HOUSE]}
