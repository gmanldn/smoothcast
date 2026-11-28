"""Event-sourced playback + receiver ownership (ARCH-07 / #695). GTK-free, pure.

Same contract as ``room_events``: validated commands -> numbered events ->
``apply`` is the only mutation, ``replay`` rebuilds the state. Adds:

* Ownership: one owner at a time; only the owner may play/pause/stop/release.
* Single poller per receiver: ``attach_poller`` fails for a second poller by
  construction, and only the attached poller's ``report`` is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybackEvent:
    seq: int
    kind: str  # claimed | released | playing | paused | stopped | position | poller_attached | poller_detached
    data: tuple


@dataclass
class PlaybackState:
    owner: str | None = None
    media: str | None = None
    status: str = "idle"  # idle | playing | paused
    position: float = 0.0
    poller: str | None = None
    revision: int = 0


def apply(state: PlaybackState, event: PlaybackEvent) -> None:
    if event.seq != state.revision + 1:
        raise ValueError(f"event {event.seq} does not follow revision {state.revision}")
    kind, data = event.kind, event.data
    if kind == "claimed":
        state.owner = data[0]
    elif kind == "released":
        state.owner, state.media, state.status, state.position = None, None, "idle", 0.0
    elif kind == "playing":
        state.media, state.status = data[0], "playing"
        state.position = data[1]
    elif kind == "paused":
        state.status = "paused"
    elif kind == "stopped":
        state.media, state.status, state.position = None, "idle", 0.0
    elif kind == "position":
        state.position = data[0]
    elif kind == "poller_attached":
        state.poller = data[0]
    elif kind == "poller_detached":
        state.poller = None
    else:
        raise ValueError(f"unknown event kind {kind!r}")
    state.revision = event.seq


def replay(events) -> PlaybackState:
    state = PlaybackState()
    for event in events:
        apply(state, event)
    return state


class PlaybackStore:
    def __init__(self) -> None:
        self.state = PlaybackState()
        self.log: list[PlaybackEvent] = []
        self._seen: dict[str, tuple[PlaybackEvent, ...]] = {}

    @classmethod
    def restore(cls, events) -> "PlaybackStore":
        """Rejoin: rebuild a store from a replayed log and keep appending to it."""
        store = cls()
        for event in events:
            apply(store.state, event)
            store.log.append(event)
        return store

    def submit(self, command_id: str, kind: str, actor: str, *args,
               expected_revision: int | None = None) -> tuple[PlaybackEvent, ...]:
        """Run a command for ``actor``; rejected or no-op commands return ``()``."""
        if command_id in self._seen:
            return self._seen[command_id]
        if expected_revision is not None and expected_revision != self.state.revision:
            return ()
        events = tuple(self._events_for(kind, actor, args))
        for event in events:
            apply(self.state, event)
            self.log.append(event)
        self._seen[command_id] = events
        return events

    def _events_for(self, kind: str, actor: str, args: tuple):
        s, seq = self.state, self.state.revision + 1
        owns = s.owner == actor
        if kind == "claim":
            if s.owner is None:
                yield PlaybackEvent(seq, "claimed", (actor,))
        elif kind == "release":
            if owns:
                yield PlaybackEvent(seq, "released", ())
        elif kind == "play":
            if owns:
                yield PlaybackEvent(seq, "playing", (args[0], float(args[1]) if len(args) > 1 else 0.0))
        elif kind == "pause":
            if owns and s.status == "playing":
                yield PlaybackEvent(seq, "paused", ())
        elif kind == "stop":
            if owns and s.status != "idle":
                yield PlaybackEvent(seq, "stopped", ())
        elif kind == "attach_poller":
            if s.poller is None:
                yield PlaybackEvent(seq, "poller_attached", (actor,))
        elif kind == "detach_poller":
            if s.poller == actor:
                yield PlaybackEvent(seq, "poller_detached", ())
        elif kind == "report":
            if s.poller == actor and s.status == "playing" and float(args[0]) != s.position:
                yield PlaybackEvent(seq, "position", (float(args[0]),))
        else:
            raise ValueError(f"unknown command {kind!r}")
