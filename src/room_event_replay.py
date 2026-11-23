"""Bounded per-participant replay for authenticated shared-room SSE.

Event IDs are a random server-run epoch and monotonic sequence. A last event ID
is a hint, never authorisation; the caller must authenticate before replay.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import re
import secrets
import threading

_HISTORY_LIMIT = 128
_FRAME_LIMIT = 65536
_ID_PATTERN = re.compile(r"([0-9a-f]{16}):([1-9][0-9]{0,18})\Z")


class RoomEventLedger:
    """Keep at most 128 small state events across all room participants."""

    def __init__(self, *, epoch: str | None = None) -> None:
        self.epoch = epoch if epoch is not None else secrets.token_hex(8)
        if re.fullmatch(r"[0-9a-f]{16}", self.epoch) is None:
            raise ValueError("Invalid room stream epoch")
        self._sequence = 0
        self._lock = threading.Lock()
        self._frames: OrderedDict[tuple[str, int], bytes] = OrderedDict()

    def publish(self, participant_id: str, payload: dict, *, resync: str | None = None) -> bytes:
        """Create an SSE frame and retain it only when below the byte cap."""
        if not participant_id:
            raise ValueError("Missing room participant")
        document = dict(payload)
        document["stream_epoch"] = self.epoch
        if resync is not None:
            document["stream_resync"] = resync
        data = json.dumps(document, separators=(",", ":"))
        with self._lock:
            self._sequence += 1
            number = self._sequence
            frame = f"id: {self.epoch}:{number}\nevent: state\ndata: {data}\n\n".encode("utf-8")
            if len(frame) <= _FRAME_LIMIT:
                self._frames[(participant_id, number)] = frame
                while len(self._frames) > _HISTORY_LIMIT:
                    self._frames.popitem(last=False)
        return frame

    def replay(self, participant_id: str, last_id: str | None) -> tuple[tuple[bytes, ...], str | None]:
        """Replay only this participant's cached successors; report gaps safely."""
        if last_id is None or last_id == "":
            return (), None
        if not isinstance(last_id, str) or len(last_id) > 48:
            return (), "invalid"
        matched = _ID_PATTERN.fullmatch(last_id)
        if matched is None:
            return (), "invalid"
        epoch, number_text = matched.groups()
        if epoch != self.epoch:
            return (), "restarted"
        number = int(number_text)
        with self._lock:
            if (participant_id, number) not in self._frames:
                return (), "gap"
            return tuple(frame for (owner, seq), frame in self._frames.items()
                         if owner == participant_id and seq > number), None

    def forget(self, participant_id: str) -> None:
        """Erase events associated with a removed room identity."""
        with self._lock:
            for key in list(self._frames):
                if key[0] == participant_id:
                    del self._frames[key]

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
