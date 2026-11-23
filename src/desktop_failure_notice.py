"""GTK-free bridge from uncaught desktop errors to bounded, civil notifications.

No GUI imports, no user data in the copied summary, and no notifications from
worker threads directly: callers supply the GTK main-context scheduler.
"""
from __future__ import annotations

from collections.abc import Callable
import re
import sys
import threading
from typing import Any

from failure_boundary import Notifier, UserFailure, describe


_EXCEPTION_TYPE = re.compile(r"[A-Za-z_][A-Za-z_0-9.]{0,63}\Z")


def copy_details(failure: UserFailure) -> str:
    """Safe clipboard summary: never copy exception arguments, paths or tokens."""
    kind = failure.detail.partition(":")[0]
    if not _EXCEPTION_TYPE.fullmatch(kind):
        kind = "Unspecified"
    return (f"SmoothCast diagnostic\nCode: {failure.code}\n"
            f"Exception type: {kind}\nTechnical details remain in the private error log.")


class DesktopFailureBridge:
    """Rate-limited notification delivery with safe uncaught-exception hooks."""

    def __init__(
        self, *, schedule: Callable[[Callable[[], bool]], Any],
        present: Callable[[UserFailure], None], alive: Callable[[], bool],
        log_glib: Callable[..., None], notifier: Notifier | None = None,
    ) -> None:
        self._schedule = schedule
        self._present = present
        self._alive = alive
        self._log_glib = log_glib
        self._notifier = notifier if notifier is not None else Notifier()
        self._lock = threading.Lock()
        self._installed = False

    def report(self, exc: BaseException | None) -> bool:
        """May be called on any thread; never raises or touches GTK directly."""
        if exc is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return False
        try:
            if not self._alive():
                return False
            failure = describe(exc)
            with self._lock:
                if not self._notifier.allow(failure):
                    return False
            self._schedule(lambda: self._deliver(failure))
            return True
        except Exception:
            # A broken UI/scheduler must not generate another uncaught error.
            return False

    def _deliver(self, failure: UserFailure) -> bool:
        try:
            if self._alive():
                self._present(failure)
        except Exception:
            # Do not recursively report a broken toast or shutting-down app.
            pass
        return False  # GLib.idle_add is strictly one-shot.

    def guard_glib(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """Catch a Python exception escaping an owned GLib idle/timer callback."""
        def guarded(*args: Any, **kwargs: Any) -> Any:
            try:
                return callback(*args, **kwargs)
            except Exception as exc:
                try:
                    self._log_glib("uncaught GLib callback exception", exc_info=True)
                except Exception:
                    pass
                self.report(exc)
                return False  # remove failing source instead of a busy loop
        return guarded

    def install_hooks(self) -> None:
        """Wrap existing error_log hooks; preserve their original log/traceback."""
        if self._installed:
            return
        self._installed = True
        previous_sys = sys.excepthook
        previous_thread = threading.excepthook
        previous_unraisable = sys.unraisablehook

        def sys_hook(exc_type: type[BaseException], exc: BaseException,
                     tb: Any) -> None:
            try:
                previous_sys(exc_type, exc, tb)
            finally:
                self.report(exc)

        def thread_hook(args: threading.ExceptHookArgs) -> None:
            try:
                previous_thread(args)
            finally:
                self.report(args.exc_value)

        def unraisable_hook(args: Any) -> None:
            try:
                previous_unraisable(args)
            finally:
                exc = getattr(args, "exc_value", None)
                if isinstance(exc, BaseException):
                    try:
                        self._log_glib("unraisable GTK/GLib callback exception",
                                       exc_info=(type(exc), exc, getattr(args, "exc_traceback", None)))
                    except Exception:
                        pass
                    self.report(exc)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook
        sys.unraisablehook = unraisable_hook
