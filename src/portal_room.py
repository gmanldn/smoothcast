"""Presence, votes and activity for SmoothCast's shared LAN room.

The GTK app remains the single owner of playback and the queue. This module is
the small, thread-safe collaboration overlay used by the existing PIN portal:
who is here, what they voted for, and what happened recently.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable
import secrets
import threading
import time

import room_activity

ONLINE_SECONDS = 45.0
MAX_PARTICIPANTS = 32
MAX_DORMANT_PARTICIPANTS = 128
PRESENCE_RETENTION_SECONDS = 8 * 60 * 60
MAX_NAME = 40
DEFAULT_ROOM_NAME = "Your room"
MAX_EVENTS = 200
MAX_TITLE = 60
MAX_TITLES = 300
COLORS = ("#6aa9ff", "#f2a65a", "#7ed6a5", "#d99cff", "#ff8d8d",
          "#72d6df", "#f4d35e", "#b8b8ff")


def clean_room_name(value: object) -> str:
    """One printable, bounded label; never a network address or identity."""
    if not isinstance(value, str):
        return DEFAULT_ROOM_NAME
    text = " ".join(value[:4096].split())
    clean = "".join(ch for ch in text if ch.isprintable())[:MAX_NAME].strip()
    return clean or DEFAULT_ROOM_NAME


class RoomError(Exception):
    def __init__(self, status: int, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


@dataclass
class Participant:
    id: str
    name: str
    color: str
    joined_at: float
    last_seen: float
    joined_order: float = 0.0  # monotonic sort key, not displayed

    def public(self, now: float) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "online": now - self.last_seen <= ONLINE_SECONDS,
            "joined_at": self.joined_at,
        }


class PortalRoom:
    def __init__(self, now: float | None = None, *,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        """Use monotonic time for expiry; wall time for human timestamps only."""
        self.clock = clock
        self.wall_clock = wall_clock
        self.created_at = clock() if now is None else now
        self._lock = threading.RLock()
        self.participants: dict[str, Participant] = {}
        # A sleeping client disappears from the live roster, but its session
        # identity remains briefly so a reconnecting browser keeps its name.
        self._dormant: dict[str, Participant] = {}
        self.votes: dict[str, set[str]] = {}
        self.events: deque[dict] = deque(maxlen=MAX_EVENTS)
        self._activity_keys: OrderedDict[tuple[str, str], float] = OrderedDict()
        self.titles: dict[str, str] = {}
        self.seq = 0
        self._name = DEFAULT_ROOM_NAME

    def set_name(self, value: object) -> bool:
        """Host-owned metadata only: retain participants, votes and history."""
        name = clean_room_name(value)
        with self._lock:
            if name == self._name:
                return False
            self._name = name
            # The existing SSE change detector observes room.seq. A rename
            # must reach joined clients even when playback and queue are idle.
            self.seq += 1
            return True

    def join(self, name: object, now: float | None = None) -> Participant:
        now = self.clock() if now is None else now
        with self._lock:
            if len(self.participants) >= MAX_PARTICIPANTS:
                raise RoomError(403, "This room is full")
            participant = Participant(
                id=secrets.token_hex(16), name=self._unique_name(name),
                color=COLORS[len(self.participants) % len(COLORS)],
                joined_at=self.wall_clock(), last_seen=now, joined_order=now,
            )
            self.participants[participant.id] = participant
            self._event("joined", participant.id, {"name": participant.name}, now)
            return participant

    def leave(self, participant_id: str, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            participant = (self.participants.pop(participant_id, None)
                           or self._dormant.pop(participant_id, None))
            if participant is None:
                return
            for voters in self.votes.values():
                voters.discard(participant_id)
            self._event("left", participant_id, {"name": participant.name}, now)

    def touch(self, participant_id: str, now: float | None = None) -> Participant:
        now = self.clock() if now is None else now
        with self._lock:
            participant = self.participants.get(participant_id)
            if participant is None:
                participant = self._dormant.pop(participant_id, None)
                if participant is not None:
                    if len(self.participants) >= MAX_PARTICIPANTS:
                        self._dormant[participant_id] = participant
                        raise RoomError(403, "This room is full")
                    self.participants[participant_id] = participant
                    self._event("joined", participant.id,
                                {"name": participant.name, "reconnected": True}, now)
            if participant is None:
                raise RoomError(401, "Your room session ended. Rejoin the room to continue.",
                                code="room.session_expired")
            participant.last_seen = now
            return participant

    def rename(self, participant_id: str, name: object,
               now: float | None = None) -> Participant:
        now = self.clock() if now is None else now
        with self._lock:
            participant = self.touch(participant_id, now)
            participant.name = self._unique_name(name, exclude_id=participant.id)
            participant.last_seen = now
            self._event("renamed", participant.id, {"name": participant.name}, now)
            return participant

    def expire_inactive(self, now: float | None = None) -> None:
        """Remove sleeping clients from the live roster, retaining brief rejoin identity."""
        now = self.clock() if now is None else now
        with self._lock:
            for participant_id, participant in list(self.participants.items()):
                if now - participant.last_seen <= ONLINE_SECONDS:
                    continue
                self.participants.pop(participant_id, None)
                self._dormant[participant_id] = participant
                self._event("left", participant_id,
                            {"name": participant.name, "expired": True}, now)
                for voters in self.votes.values():
                    voters.discard(participant_id)
            for participant_id, participant in list(self._dormant.items()):
                if now - participant.last_seen > PRESENCE_RETENTION_SECONDS:
                    self._dormant.pop(participant_id, None)
            while len(self._dormant) > MAX_DORMANT_PARTICIPANTS:
                oldest = min(self._dormant.values(), key=lambda item: item.last_seen)
                self._dormant.pop(oldest.id, None)

    def vote(self, participant_id: str, item_id: str, value: bool,
             now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        if not isinstance(value, bool):
            raise RoomError(400, "Vote must be true or false")
        with self._lock:
            participant = self.touch(participant_id, now)
            voters = self.votes.setdefault(item_id, set())
            if value:
                voters.add(participant_id)
            else:
                voters.discard(participant_id)
            vote_data = {"item_id": item_id, "votes": len(voters), "voted": value}
            if item_id in self.titles:
                vote_data["title"] = self.titles[item_id]
            self._event("voted", participant.id, vote_data, now)
            return {"item_id": item_id, "votes": len(voters), "voted": value}

    def remember(self, titles: dict[str, str]) -> None:
        """Remember display titles of queue items (already visible to everyone in the room).

        Kept after an item leaves the queue so "removed X" can still name it;
        bounded, oldest forgotten first. Never stores paths.
        """
        with self._lock:
            for item_id, title in titles.items():
                clean = " ".join(str(title or "").split())
                clean = "".join(ch for ch in clean if ch.isprintable())[:MAX_TITLE]
                if not clean or clean.startswith(("/", "~", "\\")) or clean[1:3] == ":\\":
                    self.titles.pop(item_id, None)
                    continue
                self.titles.pop(item_id, None)
                self.titles[item_id] = clean
            while len(self.titles) > MAX_TITLES:
                self.titles.pop(next(iter(self.titles)))

    def prune(self, live_item_ids: set[str]) -> None:
        with self._lock:
            for item_id in list(self.votes):
                if item_id not in live_item_ids:
                    self.votes.pop(item_id, None)

    def record(self, participant_id: str, kind: str, data: dict | None = None,
               now: float | None = None, *, command_id: str | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            # Ignore a completion racing a room reset/revocation.
            if (participant_id not in self.participants and
                    participant_id not in self._dormant and
                    participant_id not in {"someone", "system", "receiver", "host"}):
                return
            key = room_activity.command_key(participant_id, command_id)
            if key is not None:
                while self._activity_keys and next(iter(self._activity_keys.values())) <= now:
                    self._activity_keys.popitem(last=False)
                if key in self._activity_keys:
                    return  # Replayed receipt never implies a second action.
                self._activity_keys[key] = now + 120
                if len(self._activity_keys) > room_activity.MAX_COMMAND_KEYS:
                    self._activity_keys.popitem(last=False)
            self._event(kind, participant_id, data or {}, now)

    def reset_history(self) -> None:
        """Forget previous room's activity on PIN rotation; do not touch playback."""
        with self._lock:
            self.events.clear()
            self.titles.clear()
            self.votes.clear()
            self.participants.clear()
            self._dormant.clear()
            self._activity_keys.clear()
            self.seq += 1

    def snapshot(self, participant_id: str | None = None,
                 now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        with self._lock:
            me = self.participants.get(participant_id or "")
            expiry = self.wall_clock() - room_activity.MAX_EVENT_AGE
            while self.events and self.events[0]["at"] < expiry:
                self.events.popleft()
            return {
                "seq": self.seq,
                "name": self._name,
                "me": me.public(now) if me else None,
                "participants": [
                    person.public(now) for person in sorted(
                        self.participants.values(),
                        key=lambda p: (p.joined_order, p.name.casefold()))
                ],
                "activity": [{**event, "data": dict(event["data"])}
                             for event in list(self.events)[-20:]],
            }

    def _unique_name(self, name: object, *, exclude_id: str = "") -> str:
        base = " ".join(str(name or "").split())
        base = "".join(char for char in base if char.isprintable())[:MAX_NAME] or "Guest"
        used = {participant.name.casefold() for participant in
                (*self.participants.values(), *self._dormant.values())
                if participant.id != exclude_id}
        if base.casefold() not in used:
            return base
        for index in range(2, 100):
            candidate = f"{base} ({index})"
            if candidate.casefold() not in used:
                return candidate
        return f"{base} ({secrets.token_hex(2)})"

    def _event(self, kind: str, actor: str, data: dict, now: float) -> None:
        person = self.participants.get(actor) or self._dormant.get(actor)
        name = person.name if person else data.get("name", "Someone")
        item = data.get("id") or data.get("item_id")
        known_title = self.titles.get(item, "") if isinstance(item, str) else ""
        kind = kind if kind in {"action", "screen", "joined", "left", "renamed", "voted"} else "action"
        safe = room_activity.event_fields(kind, data, actor_name=name, known_title=known_title)
        self.seq += 1
        self.events.append({"seq": self.seq, "type": kind, "actor": actor,
                            "at": self.wall_clock(), "data": safe})
