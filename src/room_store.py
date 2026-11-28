"""Authoritative room queue store (ARCH-07, #695 first slice): commands in, ordered events out.

Pure and GTK-free. Every change is a command that either produces one numbered
event or is rejected; the queue is always ``replay(events)``. Idempotency keys and
revision fences are enforced here once, so adapters (window, portal, mesh) need not.
Not wired into the portal yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ADD, REMOVE, MOVE, CLEAR = "add", "remove", "move", "clear"


@dataclass(frozen=True)
class Command:
    kind: str
    key: str                       # idempotency key, unique per user intent
    item: str = ""                 # item id for add/remove/move
    title: str = ""                # add only
    index: int = -1                # move target / add position (-1 = end)
    base_revision: int | None = None   # reject if the queue moved on; None = no fence


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    item: str = ""
    title: str = ""
    index: int = -1


@dataclass
class Result:
    ok: bool
    reason: str = ""
    event: Event | None = None
    duplicate: bool = False


def apply(queue: list[tuple[str, str]], event: Event) -> list[tuple[str, str]]:
    """Pure transition; replay is a fold of this over the event log."""
    q = list(queue)
    if event.kind == ADD:
        entry = (event.item, event.title)
        q.insert(len(q) if event.index < 0 else min(event.index, len(q)), entry)
    elif event.kind == REMOVE:
        q = [e for e in q if e[0] != event.item]
    elif event.kind == MOVE:
        entry = next((e for e in q if e[0] == event.item), None)
        if entry is not None:
            q.remove(entry)
            q.insert(max(0, min(event.index, len(q))), entry)
    elif event.kind == CLEAR:
        q = []
    return q


def replay(events: list[Event]) -> list[tuple[str, str]]:
    queue: list[tuple[str, str]] = []
    for event in events:
        queue = apply(queue, event)
    return queue


@dataclass
class RoomStore:
    events: list[Event] = field(default_factory=list)
    _seen: dict = field(default_factory=dict)

    @property
    def revision(self) -> int:
        return len(self.events)

    @property
    def queue(self) -> list[tuple[str, str]]:
        return replay(self.events)

    def events_since(self, seq: int) -> list[Event]:
        """Events a client at revision ``seq`` is missing (rejoin / catch-up)."""
        return self.events[max(0, int(seq)):]

    def submit(self, cmd: Command) -> Result:
        if cmd.key in self._seen:                      # retry: same answer, no second effect
            first = self._seen[cmd.key]
            if isinstance(first, Result):              # a rejection stays rejected; use a new key to try again
                return Result(False, first.reason, duplicate=True)
            return Result(True, "duplicate", first, duplicate=True)
        result = self._decide(cmd)
        if not result.ok:
            self._seen[cmd.key] = result
        return result

    def _decide(self, cmd: Command) -> Result:
        if cmd.base_revision is not None and cmd.base_revision != self.revision:
            return Result(False, "stale_revision")
        ids = [i for i, _ in self.queue]
        if cmd.kind == ADD:
            if not cmd.item or cmd.item in ids:
                return Result(False, "duplicate_item" if cmd.item else "missing_item")
        elif cmd.kind in (REMOVE, MOVE):
            if cmd.item not in ids:
                return Result(False, "unknown_item")
        elif cmd.kind != CLEAR:
            return Result(False, "unknown_command")
        event = Event(self.revision + 1, cmd.kind, cmd.item, cmd.title, cmd.index)
        self.events.append(event)
        self._seen[cmd.key] = event
        return Result(True, event=event)


@dataclass
class Replica:
    """A client's copy (UI, portal, mesh peer): folds the event stream, never edits locally.

    Duplicate or already-seen events are ignored; a gap is refused so the caller
    re-fetches ``events_since(replica.revision)`` instead of diverging.
    """
    revision: int = 0
    queue: list[tuple[str, str]] = field(default_factory=list)

    def ingest(self, events: list[Event]) -> bool:
        for event in sorted(events, key=lambda e: e.seq):
            if event.seq <= self.revision:
                continue
            if event.seq != self.revision + 1:
                return False
            self.queue = apply(self.queue, event)
            self.revision = event.seq
        return True
