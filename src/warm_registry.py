"""Predictive warm-up registry (#423). Pure: one warm job at a time, instant cancel, 500 MB budget.

Injected: ``start(item_key, dir) -> handle`` (handle has ``cancel()`` and optional ``alive()``), ``rmtree(dir)``,
``du(dir) -> bytes``. The real FFmpeg/HLS producer plugs in behind ``start`` (streamer change is plan-first).
"""
from __future__ import annotations

TRIGGER_REMAINING_S = 60.0
BUDGET_BYTES = 500 * 1024 * 1024
HEAD_BYTES = 8 * 1024 * 1024
WARM_SEGMENTS = 3


def should_warm(next_key, current_remaining, next_changed: bool) -> bool:
    if not next_key:
        return False
    return bool(next_changed) or (current_remaining is not None and 0 <= current_remaining < TRIGGER_REMAINING_S)


class Registry:
    def __init__(self, start, rmtree, du, root: str = "warm") -> None:
        self.start, self.rmtree, self.du, self.root = start, rmtree, du, root
        self.key = self.handle = None
        self.dir = ""
        self.state = "idle"                              # idle | warming | ready
        self.log: list[str] = []

    def _dir(self, key: str) -> str:
        return f"{self.root}/{''.join(c if c.isalnum() else '_' for c in key)[:64]}"

    def request(self, key: str | None, queue_revision: int = 0) -> str:
        """Ask for ``key`` to be warm. Returns idle|warming|ready|skipped. Replaces any other job first."""
        if not key:
            self.cancel("empty")
            return "idle"
        if key == self.key and self.state in ("warming", "ready"):
            return self.state
        self.cancel("replaced")                          # never more than one warm job
        d = self._dir(key)
        try:
            self.handle = self.start(key, d)
        except Exception:
            self.rmtree(d)
            self.key = self.handle = None
            self.state = "idle"
            return "skipped"
        self.key, self.dir, self.state = key, d, "warming"
        self.log.append(f"start:{key}")
        return "warming"

    def mark_done(self, key: str) -> None:
        if key == self.key and self.state == "warming":
            self.state = "ready"
            if self.du(self.dir) > BUDGET_BYTES:         # over budget: drop it rather than fill the disk
                self.cancel("budget")

    def cancel(self, why: str = "") -> None:
        if self.handle is not None:
            try:
                self.handle.cancel()
            except Exception:
                pass
        if self.dir:
            self.rmtree(self.dir)
        if self.key:
            self.log.append(f"cancel:{self.key}:{why}")
        self.key = self.handle = None
        self.dir, self.state = "", "idle"

    def on_queue_changed(self, new_next: str | None) -> None:
        if self.key and new_next != self.key:
            self.cancel("queue_changed")

    def take(self, key: str) -> dict | None:
        """On play: hand over warm segments (skip probe + initial encode) and release ownership of the dir."""
        if key == self.key and self.state == "ready":
            out = {"dir": self.dir, "skip_probe": True, "skip_initial_encode": True, "segments": WARM_SEGMENTS}
            self.key = self.handle = None
            self.dir, self.state = "", "idle"
            return out
        if key == self.key:                              # still warming: stop it, play cold
            self.cancel("played_before_ready")
        return None
