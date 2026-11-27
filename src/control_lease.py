"""Short renewable seek/skip lease to stop control battles (#331). Pure.

Only seek/skip are gated. The first authorised request takes the lease; the
owner renews it; others get ``(False, retry_after)`` (HTTP 409). The lease is
bound to (generation, media, receiver) and dies with any change, revoke or
release, and it lapses after ``TTL_S`` of inactivity so a dropped phone never
causes a long lockout. Host can take over or release instantly.
"""
from __future__ import annotations

TTL_S = 8.0
GATED = {"seek", "skip", "next", "previous"}


class Lease:
    def __init__(self, ttl: float = TTL_S) -> None:
        self.ttl = ttl
        self.owner: str | None = None
        self.name = ""
        self.until = 0.0
        self.scope: tuple | None = None

    def _live(self, scope: tuple, now: float) -> bool:
        return self.owner is not None and self.scope == scope and now < self.until

    def request(self, actor: str, action: str, scope: tuple, now: float,
                role: str = "controller", name: str = "") -> tuple[bool, float]:
        """(allowed, retry_after_s). Non-gated actions are always allowed."""
        if action not in GATED:
            return True, 0.0
        if self._live(scope, now) and self.owner != actor and role != "host":
            return False, round(self.until - now, 1)
        keep = self.name if self.owner == actor and not name else name[:40]
        self.owner, self.name, self.scope, self.until = actor, keep, scope, now + self.ttl
        return True, 0.0

    def release(self, actor: str | None = None, *, host: bool = False) -> None:
        if actor is None or host or actor == self.owner:
            self.owner, self.name, self.scope, self.until = None, "", None, 0.0

    def revoke(self, actor: str) -> None:
        if actor == self.owner:
            self.release(actor)

    def status(self, scope: tuple, now: float) -> dict:
        """Public view: only a friendly name and countdown, no device or IP detail."""
        if not self._live(scope, now):
            return {"held": False}
        return {"held": True, "by": self.name or "Someone", "seconds_left": round(self.until - now, 1)}
