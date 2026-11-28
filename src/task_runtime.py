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

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` s, waking at once on cancel. True when cancelled (loop ``while not scope.wait(n)``)."""
        if self.cancelled:
            return True
        if self._deadline is not None:
            timeout = min(timeout, max(0.0, self._deadline - self._clock()))
        return self._cancel.wait(timeout) or self.cancelled

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
        self._daemons: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._closed = False
        self.errors: list[tuple[str, BaseException]] = []

    def scope(self, deadline: float | None = None) -> Scope:
        scope = Scope(deadline)
        with self._lock:
            if self._closed:
                scope.cancel()
            else:
                self._scopes.append(scope)
        return scope

    def submit(self, work_class: str, scope: Scope, fn: Callable[[Scope], object],
               on_done: Callable[[object, BaseException | None], None] | None = None) -> Future | None:
        """Run ``fn(scope)`` off-thread; ``on_done(result, error)`` is delivered via the dispatcher."""
        def run():
            result, error = None, None
            try:
                scope.check()
                result = fn(scope)
            except BaseException as exc:  # noqa: BLE001 - delivered to the owner, never lost
                error = exc
            if on_done is not None and not scope.cancelled and not self._closed:
                def deliver():
                    if not scope.cancelled and not self._closed:
                        on_done(result, error)
                self._deliver(deliver)

        with self._lock:
            if self._closed or scope.cancelled:
                return None
            if scope not in self._scopes:
                self._scopes.append(scope)
            future = self._pools[work_class].submit(run)
            self._futures = [f for f in self._futures if not f.done()] + [future]
        return future

    def spawn_daemon(self, name: str, scope: Scope, fn: Callable[[Scope], None], *,
                     thread_name: str | None = None) -> threading.Thread | None:
        """Own a long-lived loop (accept loop, heartbeat, watcher) on a dedicated named thread.

        Not drawn from the bounded pools, so a daemon can never starve short tasks. ``fn(scope)``
        must poll ``scope.cancelled`` (or ``scope.check()``); ``shutdown`` cancels it and joins
        within the budget. An uncaught error ends the loop and is recorded on ``errors``.
        """
        def run():
            try:
                scope.check()
                fn(scope)
            except Cancelled:
                pass
            except BaseException as exc:  # noqa: BLE001 - a dying daemon must be visible, not silent
                self.errors.append((name, exc))

        thread = threading.Thread(target=run, name=thread_name or f"sc-daemon-{name}", daemon=True)
        with self._lock:
            if self._closed or scope.cancelled:
                return None
            if scope not in self._scopes:
                self._scopes.append(scope)
            thread.start()
            self._daemons = [t for t in self._daemons if t.is_alive()] + [thread]
        return thread

    @property
    def daemon_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._daemons if t.is_alive())

    def shutdown(self, budget: float = 1.0) -> bool:
        """Cancel everything, then wait up to ``budget`` s. True when all tasks finished."""
        with self._lock:
            self._closed = True
            scopes, futures, daemons = list(self._scopes), list(self._futures), list(self._daemons)
        for scope in scopes:
            scope.cancel()
        end = time.monotonic() + budget
        clean = True
        for future in futures:
            left = end - time.monotonic()
            if left <= 0 or not _wait(future, left):
                clean = False
        for thread in daemons:
            thread.join(max(0.0, end - time.monotonic()))
            if thread.is_alive():
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
