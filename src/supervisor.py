"""Service supervisor core (ARCH-04, #692): start, health, bounded stop, restart backoff.

GTK-free and clock-injected. A service is any object with ``start()``, ``healthy()``
and ``stop()``. ``stop`` runs on a helper thread so a hung service can never hold
the caller past ``hard_stop``; the service is then abandoned and reported ``stuck``.
Wiring the portal in is a later slice.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

STOPPED, RUNNING, FAILED, STUCK = "stopped", "running", "failed", "stuck"


class Service(Protocol):
    def start(self) -> None: ...
    def healthy(self) -> bool: ...
    def stop(self) -> None: ...


@dataclass
class _Entry:
    service: Service
    graceful: float
    hard: float
    max_restarts: int
    state: str = STOPPED
    restarts: int = 0
    next_retry: float = 0.0
    last_error: str = ""


@dataclass
class Supervisor:
    clock: Callable[[], float] = time.monotonic
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    _services: dict = field(default_factory=dict)

    def add(self, name: str, service: Service, *, graceful: float = 1.0, hard: float = 3.0,
            max_restarts: int = 5) -> None:
        self._services[name] = _Entry(service, graceful, hard, max_restarts)

    def start(self, name: str) -> str:
        entry = self._services[name]
        try:
            entry.service.start()
            entry.state, entry.last_error = RUNNING, ""
        except Exception as exc:  # a service failing to start must not take the app down
            self._fail(entry, exc)
        return entry.state

    def _fail(self, entry: _Entry, exc: BaseException | str) -> None:
        entry.state, entry.last_error = FAILED, str(exc)[:200]
        entry.next_retry = self.clock() + min(self.backoff_cap, self.backoff_base * 2 ** entry.restarts)

    def tick(self) -> dict[str, str]:
        """Probe running services and restart failed ones whose backoff has elapsed."""
        for name, entry in self._services.items():
            if entry.state == RUNNING:
                try:
                    ok = entry.service.healthy()
                except Exception as exc:
                    ok = False
                    entry.last_error = str(exc)[:200]
                if not ok:
                    self._fail(entry, entry.last_error or "health probe failed")
            elif (entry.state == FAILED and entry.restarts < entry.max_restarts
                  and self.clock() >= entry.next_retry):
                entry.restarts += 1
                self.start(name)
        return self.states()

    def stop(self, name: str) -> str:
        """Stop within ``hard`` seconds; a service still stopping after that is abandoned."""
        entry = self._services[name]
        done = threading.Event()

        def run() -> None:
            try:
                entry.service.stop()
            except Exception as exc:
                entry.last_error = str(exc)[:200]
            finally:
                done.set()

        threading.Thread(target=run, daemon=True, name=f"stop-{name}").start()
        done.wait(entry.hard)
        entry.state = STOPPED if done.is_set() else STUCK
        return entry.state

    def stop_all(self) -> dict[str, str]:
        for name in list(self._services):
            self.stop(name)
        return self.states()

    def states(self) -> dict[str, str]:
        return {name: entry.state for name, entry in self._services.items()}
