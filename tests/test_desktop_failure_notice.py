"""Headless failure bridge regressions (#522): no GTK or real receiver."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import threading
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import desktop_failure_notice as notice
from failure_boundary import Notifier, UserFailure


def _bridge(*, now=None, live=None, log=None):
    queued: list = []
    shown: list = []
    alive = live if live is not None else lambda: True
    logger = log if log is not None else mock.Mock()
    notifier = Notifier(clock=lambda: now[0]) if now is not None else Notifier()
    bridge = notice.DesktopFailureBridge(
        schedule=queued.append, present=shown.append, alive=alive,
        log_glib=logger, notifier=notifier,
    )
    return bridge, queued, shown, logger


def test_worker_never_presents_on_wrong_thread_and_delivers_once():
    bridge, queued, shown, _ = _bridge()
    worker = threading.Thread(target=lambda: bridge.report(RuntimeError("secret /home/x/file.mp4")))
    worker.start()
    worker.join()
    assert len(queued) == 1 and shown == []
    assert queued.pop()() is False
    assert len(shown) == 1
    assert "secret" not in shown[0].message
    assert "/home/x/" not in shown[0].message


def test_same_failure_is_rate_limited_and_other_failures_are_bounded():
    now = [0.0]
    bridge, queued, _, _ = _bridge(now=now)
    assert sum(bridge.report(RuntimeError("bad")) for _ in range(50)) == 1
    now[0] += 31.0
    assert bridge.report(RuntimeError("bad"))
    assert len(queued) == 2


def test_queued_toast_safely_dropped_during_shutdown():
    is_open = [True]
    bridge, queued, shown, _ = _bridge(live=lambda: is_open[0])
    assert bridge.report(RuntimeError("failure"))
    is_open[0] = False
    assert queued.pop()() is False and shown == []
    assert bridge.report(RuntimeError("again")) is False


def test_glib_callback_failure_logs_original_and_does_not_repeat():
    bridge, queued, _, logger = _bridge()
    broken = bridge.guard_glib(lambda: (_ for _ in ()).throw(ValueError("private")))
    assert broken() is False
    assert len(queued) == 1
    logger.assert_called_once()
    assert logger.call_args.kwargs == {"exc_info": True}
    assert bridge.guard_glib(lambda x: x + 1)(4) == 5


def test_glib_callback_survives_broken_logger_and_presenter():
    shown = mock.Mock(side_effect=OSError("toast broken"))
    queued = []
    bridge = notice.DesktopFailureBridge(
        schedule=queued.append, present=shown, alive=lambda: True,
        log_glib=mock.Mock(side_effect=OSError("disk full")),
    )
    assert bridge.guard_glib(lambda: 1 / 0)() is False
    assert queued.pop()() is False
    assert shown.call_count == 1


def test_install_hooks_preserves_existing_handlers_and_is_idempotent():
    previous = sys.excepthook, threading.excepthook, sys.unraisablehook
    original = mock.Mock(), mock.Mock(), mock.Mock()
    sys.excepthook, threading.excepthook, sys.unraisablehook = original
    bridge, queued, _, logger = _bridge()
    try:
        bridge.install_hooks()
        installed = sys.excepthook, threading.excepthook, sys.unraisablehook
        bridge.install_hooks()
        assert installed == (sys.excepthook, threading.excepthook, sys.unraisablehook)
        exc = RuntimeError("problem")
        sys.excepthook(type(exc), exc, None)
        assert original[0].call_count == 1
        assert len(queued) == 1
        args = SimpleNamespace(exc_type=ValueError, exc_value=ValueError("worker"),
                               exc_traceback=None, thread=threading.current_thread())
        threading.excepthook(args)
        original[1].assert_called_once_with(args)
        assert len(queued) == 2
        unraisable = SimpleNamespace(exc_value=KeyError("glib"), exc_traceback=None)
        sys.unraisablehook(unraisable)
        original[2].assert_called_once_with(unraisable)
        assert logger.call_count == 1 and len(queued) == 3
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert len(queued) == 3
    finally:
        sys.excepthook, threading.excepthook, sys.unraisablehook = previous


def test_copy_details_never_includes_internal_arguments_or_paths():
    failure = UserFailure("Civil title", ("Retry",),
                          "ValueError: password=abcd C:\\Users\\amy\\secret.mp4")
    summary = notice.copy_details(failure)
    assert "Code:" in summary and "Exception type: ValueError" in summary
    assert all(secret not in summary for secret in ("password", "abcd", "Users", "amy", ".mp4"))
    hostile = UserFailure("Civil", (), "../../etc/passwd: raw")
    assert "Unspecified" in notice.copy_details(hostile)


def test_scheduler_and_alive_errors_are_contained():
    bridge = notice.DesktopFailureBridge(
        schedule=lambda _cb: (_ for _ in ()).throw(OSError("scheduler failed")),
        present=lambda _failure: None, alive=lambda: True, log_glib=mock.Mock(),
    )
    assert bridge.report(RuntimeError("x")) is False
    bridge2 = notice.DesktopFailureBridge(
        schedule=lambda _cb: None, present=lambda _f: None,
        alive=lambda: 1 / 0, log_glib=mock.Mock(),
    )
    assert bridge2.report(RuntimeError("x")) is False
