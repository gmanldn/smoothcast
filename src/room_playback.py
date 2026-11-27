"""Receiver ownership and playback as commands and events (ARCH-07, #695).

Pure and GTK-free, a sibling of ``room_store`` (queue). One owner holds the receiver;
only that owner can change playback, so two controllers cannot fight over a TV.
Idempotency keys and revision fences are enforced here once. State is
``replay(events)``. Not wired into the app yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CLAIM, RELEASE, PLAY, PAUSE, STOP = "claim", "release", "play", "pause", "stop"
IDLE, PLAYING, PAUSED = "idle", "playing", "paused"


@dataclass(frozen=True)
class Command:
    kind: str
    key: str                        # idempotency key, unique per user intent
    owner: str = ""                 # who is asking
    receiver: str = ""              # claim only
    item: str = ""                  # play only
    base_revision: int | None = None


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    owner: str = ""
    receiver: str = ""
    item: str = ""


@dataclass(frozen=True)
class State:
    owner: str = ""
    receiver: str = ""
    status: str = IDLE
    item: str = ""


@dataclass
class Result:
    ok: bool
    reason: str = ""
    event: Event | None = None
    duplicate: bool = False


def apply(state: State, event: Event) -> State:
    if event.kind == CLAIM:
        return State(owner=event.owner, receiver=event.receiver)
    if event.kind == RELEASE:
        return State()
    if event.kind == PLAY:
        return State(state.owner, state.receiver, PLAYING, event.item or state.item)
    if event.kind == PAUSE:
        return State(state.owner, state.receiver, PAUSED, state.item)
    if event.kind == STOP:
        return State(state.owner, state.receiver, IDLE, "")
    return state


def replay(events: list[Event]) -> State:
    state = State()
    for event in events:
        state = apply(state, event)
    return state


@dataclass
class RoomPlayback:
    events: list[Event] = field(default_factory=list)
    _seen: dict = field(default_factory=dict)

    @property
    def revision(self) -> int:
        return len(self.events)

    @property
    def state(self) -> State:
        return replay(self.events)

    def submit(self, cmd: Command) -> Result:
        if cmd.key in self._seen:
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
        if not cmd.owner:
            return Result(False, "missing_owner")
        state = self.state
        if cmd.kind == CLAIM:
            if not cmd.receiver:
                return Result(False, "missing_receiver")
            if state.owner and state.owner != cmd.owner:
                return Result(False, "receiver_busy")
        elif cmd.kind in (RELEASE, PLAY, PAUSE, STOP):
            if not state.owner:
                return Result(False, "no_owner")
            if state.owner != cmd.owner:
                return Result(False, "not_owner")
            if cmd.kind == PLAY and not (cmd.item or state.item):
                return Result(False, "missing_item")
            if cmd.kind == PAUSE and state.status != PLAYING:
                return Result(False, "not_playing")
        else:
            return Result(False, "unknown_command")
        event = Event(self.revision + 1, cmd.kind, cmd.owner, cmd.receiver, cmd.item)
        self.events.append(event)
        self._seen[cmd.key] = event
        return Result(True, event=event)
