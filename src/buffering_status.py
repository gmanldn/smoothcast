"""Playback phase projection for room remotes (#338). Pure.

``project`` turns watchdog/receiver facts into one phase, a short guest
message, and which actions stay allowed. ``playing`` is reported only from a
fresh *receiver* status; anything unmeasured is ``unknown`` with no invented
buffer percentage. Recovery toasts are bounded by ``Notifier``.
"""
from __future__ import annotations

import math

import errors

PHASES = ("starting", "preflighting", "waiting_first_frame", "playing", "paused", "buffering",
          "recovering", "offline", "stopped", "unknown")
FRESH_S = 10.0
MESSAGES = {
    "starting": "Starting…", "preflighting": "Checking the video…",
    "waiting_first_frame": "Waiting for the first picture…", "playing": "Playing",
    "paused": "Paused", "buffering": "Buffering…", "recovering": "Recovering. Please wait.",
    "offline": "The TV isn't responding.", "stopped": "Stopped", "unknown": "State unknown",
}
HAZARDOUS = {"play", "seek", "skip", "next", "previous"}


def _finite_number(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def project(facts: dict, now: float) -> dict:
    receiver = facts.get("receiver_state")            # PLAYING/PAUSED/BUFFERING/IDLE/None
    seen = _finite_number(facts.get("receiver_seen_at"))
    age = now - seen if seen is not None else None
    fresh = age is not None and 0 <= age <= FRESH_S
    if facts.get("recovering"):
        phase = "recovering"
    elif facts.get("stage") in ("starting", "preflighting", "waiting_first_frame"):
        phase = facts["stage"]
    elif facts.get("offline") or (receiver is not None and not fresh and facts.get("had_session")):
        phase = "offline"
    elif not fresh or receiver is None:
        phase = "unknown"
    else:
        phase = {"PLAYING": "playing", "PAUSED": "paused", "BUFFERING": "buffering",
                 "IDLE": "stopped", "STOPPED": "stopped"}.get(str(receiver).upper(), "unknown")
    ahead = _finite_number(facts.get("buffer_ahead_s"))
    raw_code = facts.get("error_code")
    code = raw_code if isinstance(raw_code, str) and raw_code in errors.CATALOGUE else ""
    out = {"phase": phase, "message": MESSAGES[phase], "at": seen if fresh else None,
           "buffer_ahead_s": round(ahead, 1) if phase in ("buffering", "playing") and fresh
           and ahead is not None and ahead >= 0 else None,
           "code": code,
           "blocked": sorted(HAZARDOUS) if phase in ("recovering", "buffering", "starting", "preflighting",
                                                      "waiting_first_frame") else []}
    out["advance_queue"] = phase == "stopped" and bool(facts.get("ended_normally"))   # offline never advances
    return out


class Notifier:
    """At most ``limit`` recovery toasts per episode; reset when playing resumes."""

    def __init__(self, limit: int = 2) -> None:
        self.limit, self.sent = limit, 0

    def should_toast(self, phase: str) -> bool:
        if phase == "playing":
            self.sent = 0
            return False
        if phase in ("recovering", "buffering", "offline") and self.sent < self.limit:
            self.sent += 1
            return True
        return False
