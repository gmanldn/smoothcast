"""Verify a direct Cast was accepted, before treating CLI exit as playback.

The caller runs this bounded probe in an existing background worker. A
receiver's explicit repeated IDLE is negative evidence; unavailable or
incomplete status is never sufficient reason to overwrite its content.
"""
from __future__ import annotations

import time
from typing import Callable

import castctl


class ForeignPlayback(RuntimeError):
    """A different known video started on the target; do not overwrite it."""


def classify(info: object, expected_title: str) -> str:
    if not isinstance(info, dict):
        return "uncertain"
    state = str(info.get("player_state") or "").upper()
    title = str(info.get("title") or "").strip()
    expected = str(expected_title or "").strip()
    if state in {"PLAYING", "PAUSED"}:
        if title and expected and title.casefold() != expected.casefold():
            return "foreign"
        # Some receivers omit titles. In that case a foreign stream cannot
        # be excluded; leave direct playback running but don't claim proof.
        return "accepted" if title and expected else "uncertain"
    if state == "IDLE":
        return "idle"
    return "uncertain"  # BUFFERING, offline, malformed or unknown


def verify_direct_start(
    device: str, title: str, *,
    get_info: Callable[[str], dict | None] = castctl.info,
    pause: Callable[[float], None] = time.sleep,
    attempts: int = 3, interval: float = 0.6,
) -> str:
    """Return accepted, rejected, or uncertain using bounded receiver polls.

    Three *consecutive* explicit IDLE replies prove a failed handoff and
    permit an HLS fallback. A confirmed foreign PLAYING/PAUSED stream raises
    ForeignPlayback and MUST NOT be replaced by an automatic fallback.
    """
    if not (1 <= attempts <= 5 and 0 <= interval <= 2):
        raise ValueError("Direct acceptance probe must be short and bounded")
    idle = 0
    for n in range(attempts):
        try:
            observed = get_info(device)
        except (OSError, ValueError, TimeoutError):
            observed = None
        status = classify(observed, title)
        if status == "foreign":
            raise ForeignPlayback("Receiver is playing different media; automatic fallback cancelled")
        if status == "accepted":
            return "accepted"
        idle = idle + 1 if status == "idle" else 0
        if n + 1 < attempts:
            pause(interval)
    return "rejected" if idle == attempts else "uncertain"
