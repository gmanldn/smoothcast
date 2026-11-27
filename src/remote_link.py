"""Reference model of the phone-remote connection life cycle (#317). Pure.

States: connected, stale, reconnecting, expired, unavailable. The web client
mirrors these rules: mutations are allowed only when ``connected``; a command
issued while not connected is *discarded* (never replayed); after any outage the
controls stay disabled until a full authoritative snapshot of the current
generation arrives; sign-in expiry never restores permissions implicitly.
"""
from __future__ import annotations

import random

CONNECTED, STALE, RECONNECTING, EXPIRED, UNAVAILABLE = (
    "connected", "stale", "reconnecting", "expired", "unavailable")
STALE_AFTER_S = 15.0        # no confirmation this long -> stale
GIVE_UP_AFTER = 8           # consecutive failures -> unavailable
BASE_S, CAP_S = 1.0, 30.0
LABELS = {CONNECTED: "Connected", STALE: "Out of date", RECONNECTING: "Reconnecting…",
          EXPIRED: "Sign in again", UNAVAILABLE: "Can't reach SmoothCast"}


def backoff(failures: int, rng: random.Random | None = None) -> float:
    """Capped exponential delay with full jitter (0.5x-1x of the ceiling)."""
    ceiling = min(CAP_S, BASE_S * (2 ** max(0, min(failures, 10))))
    return ceiling * (0.5 + 0.5 * (rng or random).random())


class Link:
    def __init__(self, now: float = 0.0) -> None:
        self.state = RECONNECTING
        self.failures = 0
        self.confirmed_at: float | None = None
        self.generation: object = None

    def snapshot_ok(self, generation: object, now: float) -> None:
        """A full authoritative snapshot arrived: only this re-enables controls."""
        if self.state == EXPIRED:
            return
        self.state, self.failures, self.confirmed_at, self.generation = CONNECTED, 0, now, generation

    def failed(self, status: int | None = None) -> None:
        if status in (401, 403):
            self.state = EXPIRED            # needs a fresh authorised login
            return
        if self.state == EXPIRED:
            return
        self.failures += 1
        self.state = UNAVAILABLE if self.failures >= GIVE_UP_AFTER else RECONNECTING

    def tick(self, now: float) -> None:
        if self.state == CONNECTED and self.confirmed_at is not None and now - self.confirmed_at > STALE_AFTER_S:
            self.state = STALE

    def signed_in_again(self) -> None:
        self.state, self.failures = RECONNECTING, 0

    def can_mutate(self) -> bool:
        return self.state == CONNECTED

    def submit(self, command: object) -> object | None:
        """The command to send now, or None when it must be discarded (never queued)."""
        return command if self.can_mutate() else None

    def label(self, now: float) -> str:
        text = LABELS[self.state]
        if self.state in (STALE, RECONNECTING, UNAVAILABLE) and self.confirmed_at is not None:
            text += f" · last confirmed {int(max(0, now - self.confirmed_at))}s ago"
        return text
