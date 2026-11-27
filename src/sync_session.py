"""Watch-together session core (#373). Pure, deterministic; clocks are passed in.

``Session`` owns the group clock: position = anchor + (server_now - at) * rate while playing.
Commands carry (client_id, command_id, generation); duplicates and stale generations are ignored.
``Clock`` does NTP-style offset estimation (lowest-RTT sample wins). ``correction`` maps drift to
ignore / rate-nudge / hard seek. Per-client track choices are not part of the shared state.
"""
from __future__ import annotations

IGNORE_S, SETTLE_S, SEEK_S, NUDGE = 0.25, 0.1, 2.0, 0.05
SEEN_MAX = 256


class Session:
    def __init__(self, item: str, duration: float, now: float) -> None:
        self.item, self.duration = item, float(duration)
        self.playing, self.rate = False, 1.0
        self.anchor, self.at = 0.0, now
        self.generation = 0
        self._seen: dict[str, None] = {}

    def position(self, now: float) -> float:
        p = self.anchor + ((now - self.at) * self.rate if self.playing else 0.0)
        return min(max(p, 0.0), self.duration)

    def state(self, now: float) -> dict:
        """The sync.state SSE payload."""
        return {"item": self.item, "playing": self.playing, "position": self.position(now), "at_server_ms": int(now * 1000),
                "rate": self.rate, "generation": self.generation}

    def command(self, client: str, command_id: str, generation: int, action: str, now: float, arg: float | None = None) -> tuple[bool, str]:
        key = f"{client}:{command_id}"
        if key in self._seen:
            return False, "duplicate"
        if generation != self.generation:
            return False, "stale"                      # client acted on an older state
        if action not in ("play", "pause", "seek"):
            return False, "unknown"
        self._seen[key] = None
        while len(self._seen) > SEEN_MAX:
            self._seen.pop(next(iter(self._seen)))
        pos = self.position(now)
        if action == "seek":
            if arg is None or arg != arg:
                return False, "bad_arg"
            pos = min(max(float(arg), 0.0), self.duration)
        self.anchor, self.at = pos, now
        self.playing = action == "play" or (action == "seek" and self.playing)
        self.generation += 1
        return True, ""

    def join(self, now: float) -> dict:
        """A late joiner starts at the current group position, never at zero."""
        return self.state(now)


class Clock:
    """Offset between a client and server clocks from ping exchanges; trusts the lowest-RTT sample."""

    def __init__(self, keep: int = 8) -> None:
        self.samples: list[tuple[float, float]] = []
        self.keep = keep

    def sample(self, t_send: float, t_server: float, t_recv: float) -> None:
        rtt = t_recv - t_send
        if rtt < 0:
            return
        self.samples.append((rtt, t_server + rtt / 2 - t_recv))
        self.samples = sorted(self.samples)[: self.keep]

    @property
    def offset(self) -> float:
        return self.samples[0][1] if self.samples else 0.0

    def server_now(self, local_now: float) -> float:
        return local_now + self.offset


def correction(drift: float, nudging: bool = False) -> dict:
    """drift = client position - group position (source seconds). Once nudging, keep going until
    drift is under SETTLE_S (hysteresis) so clients do not park just inside the dead band."""
    a = abs(drift)
    if a < (SETTLE_S if nudging else IGNORE_S):
        return {"mode": "ok", "rate": 1.0}
    if a <= SEEK_S:
        return {"mode": "nudge", "rate": 1.0 - NUDGE if drift > 0 else 1.0 + NUDGE}
    return {"mode": "seek", "rate": 1.0}
