"""Power-inhibit backends for ``sleep_inhibit.Inhibitor`` (#703). Every OS call is injected, so nothing here touches the machine in tests.

Contract: ``acquire(why) -> token`` raises on failure (the Inhibitor then proceeds unprotected); ``release(token)`` is idempotent and never raises.
"""
from __future__ import annotations

import sys
from typing import Callable

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class Fake:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail, self.active = fail, 0
        self.log: list[str] = []

    def acquire(self, why: str):
        if self.fail:
            raise OSError("inhibit refused")
        self.active += 1
        self.log.append(why)
        return object()

    def release(self, token) -> None:
        if token is not None and self.active:
            self.active -= 1


class Logind:
    """``systemd-inhibit`` held by a child process; releasing terminates it."""
    name = "logind"

    def __init__(self, spawn: Callable[[list[str]], object], which: Callable[[str], str | None]) -> None:
        self.spawn, self.which = spawn, which

    def acquire(self, why: str):
        exe = self.which("systemd-inhibit")
        if not exe:
            raise OSError("systemd-inhibit not found")
        return self.spawn([exe, "--what=sleep:shutdown", "--who=SmoothCast", f"--why={why}", "--mode=delay", "sleep", "infinity"])

    def release(self, token) -> None:
        _stop(token)


class MacCaffeinate:
    name = "caffeinate"

    def __init__(self, spawn: Callable[[list[str]], object], which: Callable[[str], str | None]) -> None:
        self.spawn, self.which = spawn, which

    def acquire(self, why: str):
        exe = self.which("caffeinate")
        if not exe:
            raise OSError("caffeinate not found")
        return self.spawn([exe, "-i"])

    def release(self, token) -> None:
        _stop(token)


class Windows:
    """SetThreadExecutionState; the callable is injected so only Windows binds the real API."""
    name = "windows"

    def __init__(self, set_state: Callable[[int], int]) -> None:
        self.set_state = set_state

    def acquire(self, why: str):
        if not self.set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            raise OSError("SetThreadExecutionState failed")
        return True

    def release(self, token) -> None:
        if token:
            try:
                self.set_state(ES_CONTINUOUS)
            except (OSError, ArithmeticError):
                pass


def _stop(proc) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
    except (OSError, ProcessLookupError):
        pass


def for_platform(platform: str = sys.platform, **injected):
    """Pick the backend for ``platform``; the caller supplies spawn/which/set_state. Unknown platforms get None (Inhibitor falls back to Noop)."""
    if platform.startswith("linux"):
        return Logind(injected["spawn"], injected["which"])
    if platform == "darwin":
        return MacCaffeinate(injected["spawn"], injected["which"])
    if platform == "win32":
        return Windows(injected["set_state"])
    return None
