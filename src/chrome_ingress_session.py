"""Pure internal ingress session transition contract for Chrome Mesh (#563).

This is NOT a Cast wire protocol and never controls a receiver. The existing
portal_commands.CommandDispatcher and CommandFence remain authoritative for
idempotent effects and playback ownership. The caller tracks sequence/epoch
and dispatches effects only after validating this transition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

MAX_REVISION = 2**63 - 1
_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_ID = re.compile(r"[A-Za-z0-9:_.-]{1,128}\Z")


class SourceKind(str, Enum):
    SEEKABLE = "seekable_media"
    LIVE = "live_mirror"
    UNSUPPORTED = "unsupported"


class Phase(str, Enum):
    IDLE = "idle"
    AUTH = "authenticating"
    NEGOTIATING = "negotiating"
    WAITING = "waiting_for_output"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPING = "stopping"
    ENDED = "ended"
    FAILED = "failed"


KINDS = frozenset(("auth_begin", "auth_ok", "negotiate", "select_output",
                   "buffer_ready", "receiver_playing", "pause", "resume",
                   "stop", "stopped", "fail"))


@dataclass(frozen=True)
class Event:
    session_id: str
    epoch: int
    sequence: int
    kind: str
    source_kind: SourceKind
    request_id: str


@dataclass(frozen=True)
class Transition:
    phase: Phase
    accepted: bool
    code: str | None = None


# An explicit, auditable transition table: no event may skip authentication,
# steal a different target session or falsely claim that buffering == playing.
_NEXT: dict[Phase, dict[str, Phase]] = {
    Phase.IDLE: {"auth_begin": Phase.AUTH},
    Phase.AUTH: {"auth_ok": Phase.NEGOTIATING},
    Phase.NEGOTIATING: {"negotiate": Phase.WAITING},
    Phase.WAITING: {"select_output": Phase.BUFFERING},
    Phase.BUFFERING: {"buffer_ready": Phase.BUFFERING,
                      "receiver_playing": Phase.PLAYING},
    Phase.PLAYING: {"pause": Phase.PAUSED},
    Phase.PAUSED: {"resume": Phase.BUFFERING,
                   "receiver_playing": Phase.PLAYING},
    Phase.STOPPING: {"stopped": Phase.ENDED},
}


def _valid(event: Event) -> bool:
    return (isinstance(event, Event)
            and isinstance(event.session_id, str) and bool(_SESSION.fullmatch(event.session_id))
            and type(event.epoch) is int and 0 <= event.epoch <= MAX_REVISION
            and type(event.sequence) is int and 0 <= event.sequence <= MAX_REVISION
            and isinstance(event.kind, str) and event.kind in KINDS
            and isinstance(event.source_kind, SourceKind)
            and isinstance(event.request_id, str) and bool(_ID.fullmatch(event.request_id)))


def advance(phase: Phase, event: Event, *, current_session: str,
            current_epoch: int, last_sequence: int) -> Transition:
    """Return a candidate state change; does no I/O, effect or deduplication.

    The enclosing controller owns the authoritative command dispatcher and
    must update last_sequence on acceptance. Ingress sequence checking alone
    does not make network commands exactly-once.
    """
    if not isinstance(phase, Phase):
        raise ValueError("Unknown ingress phase")
    if (not _valid(event) or not isinstance(current_session, str)
            or not _SESSION.fullmatch(current_session)
            or type(current_epoch) is not int or not 0 <= current_epoch <= MAX_REVISION
            or type(last_sequence) is not int or not -1 <= last_sequence <= MAX_REVISION):
        return Transition(phase, False, "invalid_event")
    if event.session_id != current_session:
        return Transition(phase, False, "session_mismatch")
    if event.epoch != current_epoch:
        return Transition(phase, False, "stale_epoch")
    if event.sequence <= last_sequence:
        return Transition(phase, False, "stale_sequence")
    if phase in (Phase.ENDED, Phase.FAILED):
        return Transition(phase, False, "terminal")
    if event.kind == "fail":
        return Transition(Phase.FAILED, True)
    if event.kind == "stop" and phase is not Phase.STOPPING:
        return Transition(Phase.STOPPING, True)
    # Unsupported sources may connect and then be rejected/stopped, but cannot
    # be presented as real playback or a usable source.
    if (event.source_kind is SourceKind.UNSUPPORTED and event.kind in
            {"select_output", "buffer_ready", "receiver_playing", "pause", "resume"}):
        return Transition(phase, False, "unsupported_source")
    next_phase = _NEXT.get(phase, {}).get(event.kind)
    if next_phase is None:
        return Transition(phase, False, "illegal_transition")
    return Transition(next_phase, True)
