"""Presence, votes and activity for SmoothCast's shared LAN room.

The GTK app remains the single owner of playback and the queue. This module is
the small, thread-safe collaboration overlay used by the existing PIN portal:
who is here, what they voted for, and what happened recently.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import secrets
import threading
import time

ONLINE_SECONDS = 45.0
MAX_PARTICIPANTS = 32
MAX_NAME = 40
MAX_EVENTS = 200
COLORS = ("#6aa9ff", "#f2a65a", "#7ed6a5", "#d99cff", "#ff8d8d",
          "#72d6df", "#f4d35e", "#b8b8ff")


class RoomError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Participant:
    id: str
    name: str
    color: str
    joined_at: float
    last_seen: float

    def public(self, now: float) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "online": now - self.last_seen <= ONLINE_SECONDS,
            "joined_at": self.joined_at,
        }


class PortalRoom:
    def __init__(self, now: float | None = None) -> None:
        self.created_at = time.time() if now is None else now
        self._lock = threading.RLock()
        self.participants: dict[str, Participant] = {}
        self.votes: dict[str, set[str]] = {}
        self.events: deque[dict] = deque(maxlen=MAX_EVENTS)
        self.seq = 0

    def join(self, name: object, now: float | None = None) -> Participant:
        now = time.time() if now is None else now
        with self._lock:
            if len(self.participants) >= MAX_PARTICIPANTS:
                raise RoomError(403, "This room is full")
            participant = Participant(
                id=secrets.token_hex(4), name=self._unique_name(name),
                color=COLORS[len(self.participants) % len(COLORS)],
                joined_at=now, last_seen=now,
            )
            self.participants[participant.id] = participant
            self._event("joined", participant.id, {"name": participant.name}, now)
            return participant

    def leave(self, participant_id: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            participant = self.participants.pop(participant_id, None)
            if participant is None:
                return
            for voters in self.votes.values():
                voters.discard(participant_id)
            self._event("left", participant_id, {"name": participant.name}, now)

    def touch(self, participant_id: str, now: float | None = None) -> Participant:
        now = time.time() if now is None else now
        with self._lock:
            participant = self.participants.get(participant_id)
            if participant is None:
                raise RoomError(401, "Join the room again")
            participant.last_seen = now
            return participant

    def vote(self, participant_id: str, item_id: str, value: bool,
             now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if not isinstance(value, bool):
            raise RoomError(400, "Vote must be true or false")
        with self._lock:
            participant = self.touch(participant_id, now)
            voters = self.votes.setdefault(item_id, set())
            if value:
                voters.add(participant_id)
            else:
                voters.discard(participant_id)
            self._event("voted", participant.id,
                        {"item_id": item_id, "votes": len(voters)}, now)
            return {"item_id": item_id, "votes": len(voters), "voted": value}

    def prune(self, live_item_ids: set[str]) -> None:
        with self._lock:
            for item_id in list(self.votes):
                if item_id not in live_item_ids:
                    self.votes.pop(item_id, None)

    def record(self, participant_id: str, kind: str, data: dict | None = None,
               now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._event(kind, participant_id, data or {}, now)

    def snapshot(self, participant_id: str | None = None,
                 now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            me = self.participants.get(participant_id or "")
            return {
                "seq": self.seq,
                "me": me.public(now) if me else None,
                "participants": [
                    person.public(now) for person in sorted(
                        self.participants.values(),
                        key=lambda p: (p.joined_at, p.name.casefold()))
                ],
                "activity": list(self.events)[-20:],
            }

    def _unique_name(self, name: object) -> str:
        base = " ".join(str(name or "").split())
        base = "".join(char for char in base if char.isprintable())[:MAX_NAME] or "Guest"
        used = {participant.name.casefold() for participant in self.participants.values()}
        if base.casefold() not in used:
            return base
        for index in range(2, 100):
            candidate = f"{base} ({index})"
            if candidate.casefold() not in used:
                return candidate
        return f"{base} ({secrets.token_hex(2)})"

    def _event(self, kind: str, actor: str, data: dict, now: float) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, "type": kind, "actor": actor,
                            "at": now, "data": data})
