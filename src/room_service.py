"""One JSON facade over RoomStore (queue) and RoomPlayback (ownership) for portal, GTK and mesh adapters (#695).

Every surface sends the same dict and gets the same dict back, so they cannot disagree about rules.
Thread-safe behind one lock; payload fields are type- and length-checked before any command is built.
"""
from __future__ import annotations

import threading

import room_playback as rp
import room_store as rs

QUEUE_KINDS = frozenset({"add", "remove", "move", "clear"})
PLAYBACK_KINDS = frozenset({rp.CLAIM, rp.RELEASE, rp.PLAY, rp.PAUSE, rp.STOP})
MAX_FIELD = 512


def _text(payload: dict, name: str) -> str | None:
    value = payload.get(name, "")
    return value if isinstance(value, str) and len(value) <= MAX_FIELD else None


def _int(payload: dict, name: str, default):
    value = payload.get(name, default)
    return value if (value is default or (isinstance(value, int) and not isinstance(value, bool))) else None


class RoomService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.queue = rs.RoomStore()
        self.playback = rp.RoomPlayback()

    def command(self, payload) -> dict:
        """Apply one command dict. Returns ``{ok, reason, duplicate, revision}``; never raises on bad input."""
        if not isinstance(payload, dict):
            return self._reject("bad_payload")
        kind, key = payload.get("kind"), _text(payload, "key")
        if not isinstance(kind, str) or not key:
            return self._reject("bad_payload")
        fields = {n: _text(payload, n) for n in ("item", "title", "owner", "receiver")}
        index, base = _int(payload, "index", -1), _int(payload, "base_revision", None)
        if None in fields.values() or index is None or (payload.get("base_revision") is not None and base is None):
            return self._reject("bad_payload")
        with self._lock:
            if kind in QUEUE_KINDS:
                result = self.queue.submit(rs.Command(kind, key, fields["item"], fields["title"], index, base))
                revision = self.queue.revision
            elif kind in PLAYBACK_KINDS:
                result = self.playback.submit(rp.Command(kind, key, fields["owner"], fields["receiver"], fields["item"], base))
                revision = self.playback.revision
            else:
                return self._reject("unknown_kind")
        return {"ok": result.ok, "reason": result.reason, "duplicate": result.duplicate, "revision": revision}

    def snapshot(self) -> dict:
        with self._lock:
            state = self.playback.state
            return {
                "queue": {"revision": self.queue.revision, "items": [{"item": i, "title": t} for i, t in self.queue.queue]},
                "playback": {"revision": self.playback.revision, "owner": state.owner, "receiver": state.receiver,
                             "status": state.status, "item": state.item},
            }

    @staticmethod
    def _reject(reason: str) -> dict:
        return {"ok": False, "reason": reason, "duplicate": False, "revision": -1}
