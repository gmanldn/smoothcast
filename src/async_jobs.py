"""Bounded, GTK-free work queues for responsive SmoothCast background tasks.

GTK owns the main context.  Jobs run in daemon threads; result callbacks are
*scheduled* through an injected main-context dispatcher, never called by a
worker.  Slow transcoding cannot occupy the status or transport domain.
"""
from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
import threading
from typing import Callable

import command_trace

# (workers, waiting jobs).  Short control/status work cannot queue behind
# FFmpeg conversion or library scanning.  No new runtime dependency.
DEFAULT_LIMITS = {
    "transport": (2, 8),
    "status": (2, 6),
    "discovery": (1, 2),
    # Interactive receiver handoff must not queue behind previews or file copies.
    "cast_start": (1, 2),
    "media": (2, 4),
    "background": (2, 8),
}
def thread_inventory() -> tuple[str, ...]:
    """Snapshot Python-visible threads; liveness is not a health guarantee."""
    rows = []
    for thread in threading.enumerate():
        if not thread.is_alive():
            continue
        ident = thread.native_id
        role = ("main" if thread is threading.main_thread()
                else "daemon" if thread.daemon else "worker")
        rows.append((thread.name, ident or 0,
                     f"{thread.name} · TID {ident if ident is not None else 'unknown'} · {role} · alive"))
    return tuple(row[2] for row in sorted(rows))


_STOP = object()
_FAILURE_MESSAGES = {
    "transport": "Check that the receiver is connected, then try again.",
    "status": "Could not check the receiver. Check its power and network connection.",
    "discovery": "Could not scan for receivers. Check your network and scan again.",
    "media": "Check that the media file is available and try again.",
    "cast_start": "Could not start playback. Check the receiver and media file, then retry.",
}
_DEFAULT_FAILURE = "SmoothCast could not complete the action. Try again."


@dataclass(frozen=True)
class _Job:
    work: Callable
    done: Callable | None
    failed: Callable | None
    valid: Callable[[], bool] | None
    trace_id: str | None = None


class WorkRejected(RuntimeError):
    """A bounded domain cannot accept another task right now."""


class UserFacingError(RuntimeError):
    """An expected failure with copy reviewed for display and optional private detail."""

    default_code = "internal.unexpected"

    def __init__(self, message: str, *, detail: str | None = None, code: str | None = None) -> None:
        super().__init__(message if not detail else f"{message} {detail}")
        self.user_message = message
        self.code = code or self.default_code  # stable, untranslated (docs/ERRORS.md)


class WorkDomains:
    """Lazily start bounded, named daemon workers per independent I/O domain.

    `dispatch(callback)` must enqueue onto the GTK main context in production.
    `valid()` is evaluated *on that context*, immediately before delivery.
    Failure callbacks receive display-safe copy. Private exception details are
    available to the error logger.
    Shutdown cancels queued jobs and discards late results, without blocking
    on media/receiver subprocesses that may still be running.
    """

    def __init__(
        self,
        dispatch: Callable[[Callable], object],
        *,
        on_error: Callable | None = None,
        limits: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._on_error = on_error
        specs = dict(DEFAULT_LIMITS if limits is None else limits)
        if not specs or any(
            not name or workers < 1 or pending < workers
            for name, (workers, pending) in specs.items()
        ):
            raise ValueError("Every work domain needs workers >= 1 and queue >= workers")
        self._queues = {name: Queue(maxsize=pending) for name, (_, pending) in specs.items()}
        self._workers = {name: [] for name in specs}
        self._limits = specs
        self._lock = threading.Lock()
        self._closed = False

    def _log(self, message: str, *, exc_info: bool = False) -> None:
        if self._on_error is not None:
            try:
                self._on_error(message, exc_info=exc_info)
            except Exception:
                pass  # Logging must not strand a worker or the GTK event loop.

    def _schedule(
        self, callback: Callable | None, value: object,
        valid: Callable[[], bool] | None,
    ) -> None:
        if callback is None:
            return

        def deliver() -> bool:
            if self._closed:
                return False
            try:
                if valid is None or valid():
                    callback(value)
            except Exception:
                self._log("Async callback failed", exc_info=True)
            return False  # GLib.idle_add is one-shot, not a repeating timer.

        try:
            self._dispatch(deliver)
        except Exception:
            self._log("Async main-context dispatch failed", exc_info=True)

    def _worker(self, domain: str) -> None:
        tasks = self._queues[domain]
        while True:
            job = tasks.get()
            try:
                if job is _STOP:
                    return
                if self._closed:
                    continue
                try:
                    value = job.work()
                except Exception as exc:
                    suffix = f" [command:{job.trace_id}]" if job.trace_id else ""
                    self._log(f"Async {domain} work failed{suffix}", exc_info=True)
                    expected = exc if isinstance(exc, UserFacingError) else exc.__cause__
                    message = (expected.user_message if isinstance(expected, UserFacingError)
                               else _FAILURE_MESSAGES.get(domain, _DEFAULT_FAILURE))
                    self._schedule(job.failed, message, job.valid)
                else:
                    self._schedule(job.done, value, job.valid)
            finally:
                tasks.task_done()

    def submit(
        self, work: Callable, *, done: Callable | None = None,
        failed: Callable | None = None, domain: str = "background",
        valid: Callable[[], bool] | None = None,
    ) -> bool:
        """Never wait for a queue slot on GTK. Failure is delivered via idle."""
        if domain not in self._queues:
            raise ValueError(f"Unknown Async work domain: {domain}")
        rejection = None
        with self._lock:
            if self._closed:
                return False  # No callbacks after application shutdown.
            queue = self._queues[domain]
            # Start workers before enqueue, so the first task is always
            # serviced even when a worker must first acquire the GIL.
            if not self._workers[domain]:
                for index in range(self._limits[domain][0]):
                    thread = threading.Thread(
                        target=self._worker, args=(domain,),
                        name=f"smoothcast-{domain}-{index + 1}", daemon=True,
                    )
                    thread.start()
                    self._workers[domain].append(thread)
            try:
                queue.put_nowait(_Job(
                    command_trace.propagate(work) or work,
                    command_trace.propagate(done),
                    command_trace.propagate(failed),
                    valid,
                    command_trace.current_id(),
                ))
                command_trace.stage("worker_queued")
            except Full:
                rejection = f"{domain.capitalize()} work queue is busy; retry shortly"
        if rejection is not None:
            self._log(rejection)
            self._schedule(failed, rejection, valid)
            return False
        return True

    def shutdown(self) -> None:
        """Reject new tasks, discard queued tasks/results; never join a slow TV."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for domain, tasks in self._queues.items():
                while True:
                    try:
                        tasks.get_nowait()
                    except Empty:
                        break
                    tasks.task_done()
                for _ in self._workers[domain]:
                    tasks.put_nowait(_STOP)
