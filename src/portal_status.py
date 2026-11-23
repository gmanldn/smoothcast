"""GTK-free publication of detached room status for HTTP readers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import threading
import time
from typing import Callable


@dataclass(frozen=True)
class _Published:
    version: int
    at: float
    state: dict


class PublishedStatus:
    """Atomic immutable-by-contract status value with monotonic age metadata.

    ``publish`` detaches the GTK-owned tree. ``read`` returns a fresh mutable
    copy for HTTP response enrichment, so no reader can change the published
    value or any other reader's result.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._version = 0
        self._current: _Published | None = None

    def publish(self, state: dict) -> int:
        detached = deepcopy(state)
        with self._lock:
            self._version += 1
            current = _Published(self._version, self._clock(), detached)
            self._current = current
            return current.version

    def peek(self) -> tuple[int, dict] | None:
        """(version, state) WITHOUT copying. Read-only: callers must not mutate the tree."""
        with self._lock:
            current = self._current
        return None if current is None else (current.version, current.state)

    def read(self) -> dict | None:
        with self._lock:
            current = self._current
        if current is None:
            return None
        result = deepcopy(current.state)
        result["snapshot_version"] = current.version
        result["snapshot_age_ms"] = max(0, int((self._clock() - current.at) * 1000))
        return result
