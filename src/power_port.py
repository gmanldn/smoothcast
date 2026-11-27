"""PowerManager port (ARCH-15, #703): OS sleep-inhibit backends behind ``sleep_inhibit.Inhibitor``.

Each backend has ``acquire(why) -> token`` and ``release(token)``, the interface
``Inhibitor`` already expects. Process spawning and OS calls are injected, so this
module imports nothing OS-specific and every backend is testable with fakes.
A backend that cannot start returns ``None`` (nothing held) instead of raising.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable

import sleep_inhibit

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _stop(process) -> None:
    try:
        process.terminate()
    except Exception:  # noqa: BLE001 - releasing must never raise
        pass


@dataclass
class SystemdInhibit:
    """Linux: hold a logind delay lock for as long as a helper process lives."""
    spawn: Callable[[list[str]], object]
    name: str = "systemd-inhibit"

    def acquire(self, why: str):
        try:
            return self.spawn(["systemd-inhibit", "--what=sleep:shutdown", "--who=SmoothCast",
                               f"--why={why}", "--mode=delay", "sleep", "infinity"])
        except OSError:
            return None

    def release(self, token) -> None:
        if token is not None:
            _stop(token)


@dataclass
class Caffeinate:
    """macOS: ``caffeinate -i`` keeps the system awake while it runs."""
    spawn: Callable[[list[str]], object]
    name: str = "caffeinate"

    def acquire(self, why: str):
        try:
            return self.spawn(["caffeinate", "-i"])
        except OSError:
            return None

    def release(self, token) -> None:
        if token is not None:
            _stop(token)


@dataclass
class WindowsExecutionState:
    """Windows: SetThreadExecutionState, injected so no ctypes import is needed here."""
    set_state: Callable[[int], int]
    name: str = "execution-state"

    def acquire(self, why: str):
        return True if self.set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) else None

    def release(self, token) -> None:
        if token is not None:
            self.set_state(ES_CONTINUOUS)


@dataclass
class Fake:
    name: str = "fake"
    held: list = field(default_factory=list)
    released: list = field(default_factory=list)

    def acquire(self, why: str):
        token = object()
        self.held.append(why)
        return token

    def release(self, token) -> None:
        self.released.append(token)


def choose(platform: str = sys.platform, *, spawn=None, set_state=None):
    """Backend for this OS from what the caller can provide; the no-op backend otherwise."""
    if platform.startswith("linux") and spawn:
        return SystemdInhibit(spawn)
    if platform == "darwin" and spawn:
        return Caffeinate(spawn)
    if platform.startswith("win") and set_state:
        return WindowsExecutionState(set_state)
    return sleep_inhibit.NoopBackend()
