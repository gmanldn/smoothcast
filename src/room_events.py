"""Event-sourced queue store (ARCH-07 / #695 first slice). GTK-free, pure.

Every queue change is a command that is validated once, centrally, and
produces numbered, replayable events. State is only ever changed by
``apply``; ``replay(events)`` therefore rebuilds the identical state.

* Idempotency: a repeated ``command_id`` returns the original events and
  changes nothing.
* Revision fence: ``expected_revision`` (optional) rejects a stale edit.
"""
from __future__ import annotations

from typing import Protocol
from dataclasses import dataclass, replace, field


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str  # "added" | "removed" | "moved" | "cleared" | "replaced"
    data: tuple
    cid: str = ""  # command id that produced it ("" for outside edits), kept so idempotency survives a rejoin


@dataclass
class QueueState:
    items: list[str] = field(default_factory=list)
    revision: int = 0


def apply(state: QueueState, event: Event) -> None:
    """The only mutation path for ``QueueState``."""
    if event.seq != state.revision + 1:
        raise ValueError(f"event {event.seq} does not follow revision {state.revision}")
    if event.kind == "added":
        state.items.extend(event.data)
    elif event.kind == "removed":
        del state.items[event.data[0]]
    elif event.kind == "moved":
        src, dst = event.data
        state.items.insert(dst, state.items.pop(src))
    elif event.kind == "replaced":
        state.items[:] = event.data
    elif event.kind == "cleared":
        state.items.clear()
    else:
        raise ValueError(f"unknown event kind {event.kind!r}")
    state.revision = event.seq


def replay(events) -> QueueState:
    state = QueueState()
    for event in events:
        apply(state, event)
    return state


def store_for(window) -> "QueueStore":
    """The window's store, bound to its live ``queue`` list (re-adopted if the list is replaced)."""
    store = getattr(window, "_queue_store", None)
    if store is None:
        store = window._queue_store = QueueStore(window.queue)
    store.sync(window.queue)
    return store


class QueuePort(Protocol):
    """What the portal, mesh and window need from a queue: commands in, state out (#691).

    ``QueueStore`` is the real implementation; tests use a fake with the same surface."""
    state: QueueState

    def submit(self, command_id: str, kind: str, *args, expected_revision: int | None = None) -> tuple: ...


class QueueStore:
    """Validated commands -> ordered events -> state."""

    def __init__(self, items: list[str] | None = None) -> None:
        """``items`` adopts a live list in place (the window's ``queue``) so every holder keeps seeing it."""
        self.state = QueueState(items if items is not None else [])
        self.log: list[Event] = []
        self._seen: dict[str, tuple[Event, ...]] = {}
        self._snapshot: tuple[str, ...] = ()
        self.sync(self.state.items)  # adopting a non-empty list starts the log with its contents

    @classmethod
    def restore(cls, events) -> "QueueStore":
        """Rejoin: rebuild a store from a replayed log and keep appending to it."""
        store = cls()
        for event in events:
            apply(store.state, event)
            store.log.append(event)
            if event.cid:
                store._seen[event.cid] = store._seen.get(event.cid, ()) + (event,)
        store._snapshot = tuple(store.state.items)
        return store

    def sync(self, live: list[str]) -> None:
        """Record edits made outside the store (or a replaced list) as one ``replaced`` event."""
        if live is self.state.items and tuple(live) == self._snapshot:
            return
        event = Event(self.state.revision + 1, "replaced", tuple(live))
        self.state.items = live
        self.state.revision = event.seq
        self.log.append(event)
        self._snapshot = tuple(live)

    def submit(self, command_id: str, kind: str, *args,
               expected_revision: int | None = None) -> tuple[Event, ...]:
        """Run a command; returns the events it produced (empty for a no-op or rejection)."""
        self.sync(self.state.items)  # outside edits since the last command become an event first
        if command_id in self._seen:
            return self._seen[command_id]
        if expected_revision is not None and expected_revision != self.state.revision:
            return ()  # stale: not remembered, so the caller may retry with a fresh fence
        events = tuple(replace(e, cid=command_id) for e in self._events_for(kind, args))  # may be empty: a validated no-op
        for event in events:
            apply(self.state, event)
            self.log.append(event)
        self._snapshot = tuple(self.state.items)
        self._seen[command_id] = events
        return events

    def _events_for(self, kind: str, args: tuple):
        seq = self.state.revision + 1
        items = self.state.items
        if kind == "add":
            new = tuple(dict.fromkeys(p for p in args[0] if p not in items))
            if new:
                yield Event(seq, "added", new)
        elif kind == "remove":
            index = args[0]
            if 0 <= index < len(items):
                yield Event(seq, "removed", (index,))
        elif kind == "move":
            src, dst = args
            if 0 <= src < len(items) and 0 <= dst < len(items) and src != dst:
                yield Event(seq, "moved", (src, dst))
        elif kind == "clear":
            if items:
                yield Event(seq, "cleared", ())
        else:
            raise ValueError(f"unknown command {kind!r}")
