"""Bounded task runtime (ARCH-08, #696 first slice).

Executors per work class cap concurrency. Every task runs in a ``Scope`` that
carries a cancel flag and a deadline; ``Runtime.shutdown`` cancels all scopes and
waits at most ``budget`` seconds, never blocking the caller longer. Results go
through an injected ``deliver`` (the GTK dispatcher in the app) so UI updates stay
on one coalescing path. GTK-free.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

LIMITS = {"network": 4, "disk": 2, "cpu": 2, "media": 2}


class Cancelled(Exception):
    pass


class Scope:
    """Owner of related tasks: cancel once, every task sees it."""

    def __init__(self, deadline: float | None = None, clock: Callable[[], float] = time.monotonic):
        self._cancel = threading.Event()
        self._clock = clock
        self._deadline = None if deadline is None else clock() + deadline

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set() or (self._deadline is not None and self._clock() >= self._deadline)

    def check(self) -> None:
        """Cooperative cancellation point for long tasks."""
        if self.cancelled:
            raise Cancelled()


class Runtime:
    def __init__(self, deliver: Callable[[Callable[[], None]], None] | None = None,
                 limits: dict[str, int] | None = None):
        self._deliver = deliver or (lambda fn: fn())
        self._pools = {k: ThreadPoolExecutor(max_workers=n, thread_name_prefix=f"sc-{k}")
                       for k, n in (limits or LIMITS).items()}
        self._scopes: list[Scope] = []
        self._futures: list[Future] = []
        self._lock = threading.Lock()
        self._closed = False

    def scope(self, deadline: float | None = None) -> Scope:
        scope = Scope(deadline)
        with self._lock:
            self._scopes.append(scope)
        return scope

    def submit(self, work_class: str, scope: Scope, fn: Callable[[Scope], object],
               on_done: Callable[[object, BaseException | None], None] | None = None) -> Future | None:
        """Run ``fn(scope)`` off-thread; ``on_done(result, error)`` is delivered via the dispatcher."""
        if self._closed or scope.cancelled:
            return None

        def run():
            result, error = None, None
            try:
                scope.check()
                result = fn(scope)
            except BaseException as exc:  # noqa: BLE001 - delivered to the owner, never lost
                error = exc
            if on_done is not None and not (scope.cancelled and isinstance(error, Cancelled)):
                self._deliver(lambda: on_done(result, error))

        future = self._pools[work_class].submit(run)
        with self._lock:
            self._futures = [f for f in self._futures if not f.done()] + [future]
        return future

    def shutdown(self, budget: float = 1.0) -> bool:
        """Cancel everything, then wait up to ``budget`` s. True when all tasks finished."""
        self._closed = True
        with self._lock:
            scopes, futures = list(self._scopes), list(self._futures)
        for scope in scopes:
            scope.cancel()
        end = time.monotonic() + budget
        clean = True
        for future in futures:
            left = end - time.monotonic()
            if left <= 0 or not _wait(future, left):
                clean = False
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        return clean


def _wait(future: Future, timeout: float) -> bool:
    try:
        future.result(timeout)
    except TimeoutError:
        return False
    except BaseException:  # noqa: BLE001 - task errors are already delivered
        return True
    return True


_SHARED: Runtime | None = None
_SHARED_LOCK = threading.Lock()


def shared() -> Runtime:
    """Process-wide runtime; the app may call ``configure(deliver)`` first to route results to GTK."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = Runtime()
        return _SHARED


def configure(deliver: Callable[[Callable[[], None]], None]) -> Runtime:
    """Install the shared runtime with a UI dispatcher (idempotent: replaces only an unused default)."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = Runtime(deliver)
        return _SHARED
