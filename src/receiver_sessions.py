"""Registry of independent per-receiver sessions (#132). Pure; no I/O.

Each receiver owns one session: its own stream token (so URLs never overlap),
media, state and last error. Stopping, seeking or failing one session cannot
touch another, and a stale token can never act on a newer session.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, replace

STATES = ("idle", "starting", "playing", "paused", "error")
MAX_SESSIONS = 8


@dataclass(frozen=True)
class Session:
    receiver: str
    token: str
    media: str
    state: str = "starting"
    position: float = 0.0
    error: str = ""


class Sessions:
    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._by_receiver: dict[str, Session] = {}
        self._max = max_sessions

    def start(self, receiver: str, media: str) -> Session | None:
        """Begin (replacing any earlier session for the same receiver); None at the cap."""
        if receiver not in self._by_receiver and len(self._by_receiver) >= self._max:
            return None
        s = Session(receiver, secrets.token_urlsafe(16), media)
        self._by_receiver[receiver] = s
        return s

    def _owned(self, receiver: str, token: str) -> Session | None:
        s = self._by_receiver.get(receiver)
        return s if s and secrets.compare_digest(s.token, str(token)) else None

    def update(self, receiver: str, token: str, **changes) -> bool:
        s = self._owned(receiver, token)
        if s is None or changes.get("state", s.state) not in STATES:
            return False
        allowed = {k: v for k, v in changes.items() if k in ("state", "position", "error")}
        self._by_receiver[receiver] = replace(s, **allowed)
        return True

    def fail(self, receiver: str, token: str, message: str) -> bool:
        return self.update(receiver, token, state="error", error=str(message)[:200])

    def stop(self, receiver: str, token: str | None = None) -> bool:
        """Stop one receiver; a given token must match."""
        s = self._by_receiver.get(receiver)
        if s is None or (token is not None and self._owned(receiver, token) is None):
            return False
        del self._by_receiver[receiver]
        return True

    def resolve(self, token: str) -> Session | None:
        """Session for a stream URL token, or None (unknown/expired)."""
        for s in self._by_receiver.values():
            if secrets.compare_digest(s.token, str(token)):
                return s
        return None

    def get(self, receiver: str) -> Session | None:
        return self._by_receiver.get(receiver)

    def active(self) -> list[Session]:
        return list(self._by_receiver.values())
