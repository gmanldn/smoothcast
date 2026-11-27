"""House memory (#433): a shared 'what did we watch' log, separate from personal history. Pure + atomic JSON.

Append on playback start, finalise on stop; plays under 60 s watched are removed. Retention: 2 years or
20 000 events. Private-room events are visible to the room's owners only (stricter than control: even the
host does not see them here); guests get titles hidden. The host can clear everything. No analytics.
"""
from __future__ import annotations

import json
import store
import time as _time
from pathlib import Path

MIN_WATCHED_S, MAX_EVENTS, MAX_AGE_S, PAGE = 60, 20_000, 2 * 365 * 86400, 50
HIDDEN_TITLE = "Something"


class History:
    def __init__(self, path: Path | None = None, clock=None) -> None:
        self.path, self.clock = (Path(path) if path else None), clock or _time.time
        self.events: list[dict] = []
        self.seq = 0
        if self.path:
            try:
                d = json.loads(self.path.read_text("utf-8"))
                self.events = [e for e in d.get("events", []) if isinstance(e, dict) and isinstance(e.get("seq"), int) and e.get("watched_seconds") is not None]
                self.seq = max([e["seq"] for e in self.events] + [int(d.get("seq", 0))])
            except (OSError, ValueError, AttributeError):
                pass

    def start(self, room: dict, item: dict, resident: str | None = None) -> int:
        self.seq += 1
        self.events.append({"seq": self.seq, "ts": self.clock(), "room_id": str(room.get("id", ""))[:64], "room": str(room.get("name", ""))[:60],
                            "private_to": list(room.get("private_to") or [])[:20], "content_key": str(item.get("content_key", ""))[:128],
                            "title": str(item.get("title", ""))[:200], "resident": resident, "watched_seconds": None})
        self._prune()
        self._save()
        return self.seq

    def stop(self, seq: int, watched_seconds: float) -> bool:
        for i, e in enumerate(self.events):
            if e["seq"] == seq:
                if not isinstance(watched_seconds, (int, float)) or watched_seconds < MIN_WATCHED_S:
                    del self.events[i]                   # very short plays are never recorded
                else:
                    e["watched_seconds"] = int(watched_seconds)
                self._save()
                return True
        return False

    def visible(self, e: dict, actor: str | None, role: str) -> bool:
        owners = e.get("private_to") or []
        return not owners or actor in owners

    def listing(self, actor: str | None, role: str, cursor: int | None = None, limit: int = PAGE, privacy: str = "full") -> dict:
        """GET /api/house-history?cursor= — newest first; cursor = last seq seen."""
        limit = max(1, min(int(limit), 200))
        rows = [e for e in reversed(self.events) if e["watched_seconds"] is not None and (cursor is None or e["seq"] < cursor) and self.visible(e, actor, role)]
        page, more = rows[:limit], len(rows) > limit
        hide = role == "guest" or privacy != "full"
        out = [{"seq": e["seq"], "ts": e["ts"], "room_id": e["room_id"], "room": e["room"], "title": HIDDEN_TITLE if hide else e["title"],
                "content_key": None if hide else e["content_key"], "watched_seconds": e["watched_seconds"], "resident": None if hide else e["resident"]} for e in page]
        return {"events": out, "next_cursor": page[-1]["seq"] if more and page else None}

    def clear(self, role: str) -> bool:
        if role != "host":
            return False
        self.events = []
        self._save()
        return True

    def _prune(self) -> None:
        cutoff = self.clock() - MAX_AGE_S
        self.events = [e for e in self.events if e["ts"] >= cutoff][-MAX_EVENTS:]

    def _save(self) -> None:
        if not self.path:
            return
        store.Store(self.path).write({"version": 1, "seq": self.seq, "events": self.events})  # atomic, owner-only (#701)


def group_by_day_room(events: list[dict], tz_offset_s: int = 0) -> list[dict]:
    """History tab: [{day:'YYYY-MM-DD', rooms:[{room, events:[...]}]}], newest day first."""
    days: dict[str, dict[str, list]] = {}
    for e in events:
        day = _time.strftime("%Y-%m-%d", _time.gmtime(e["ts"] + tz_offset_s))
        days.setdefault(day, {}).setdefault(e["room"], []).append(e)
    return [{"day": d, "rooms": [{"room": r, "events": v} for r, v in rooms.items()]} for d, rooms in sorted(days.items(), reverse=True)]
