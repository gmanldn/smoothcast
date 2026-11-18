"""Tests for src/error_log.py ring-buffer error logger."""

import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import error_log  # noqa: E402


def test_add_and_read(tmp_path):
    log_file = tmp_path / "errors.log"
    el = error_log.ErrorLog(log_file)
    el.add("first")
    el.add("second")
    lines = el.read()
    assert len(lines) == 2
    assert lines[0].endswith("  first")
    assert lines[1].endswith("  second")


def test_contains_message_and_timestamp(tmp_path):
    log_file = tmp_path / "errors.log"
    el = error_log.ErrorLog(log_file)
    el.add("hello world")
    text = "\n".join(el.read())
    assert "hello world" in text
    assert "T" in text  # ISO timestamp present


def test_ring_buffer_caps_at_max_lines(tmp_path):
    log_file = tmp_path / "errors.log"
    el = error_log.ErrorLog(log_file)
    for i in range(error_log.MAX_LINES + 50):
        el.add(f"msg {i}")
    lines = el.read()
    assert len(lines) == error_log.MAX_LINES
    assert lines[0].endswith(f"msg {50}")
    assert lines[-1].endswith(f"msg {error_log.MAX_LINES + 49}")


def test_exc_info_records_traceback(tmp_path):
    log_file = tmp_path / "errors.log"
    el = error_log.ErrorLog(log_file)
    try:
        raise ValueError("kaboom")
    except Exception:
        el.add("failed", exc_info=True)
    text = "\n".join(el.read())
    assert "ValueError: kaboom" in text
    assert "Traceback" in text


def test_clear_empties_log(tmp_path):
    log_file = tmp_path / "errors.log"
    el = error_log.ErrorLog(log_file)
    el.add("a")
    el.clear()
    assert el.read() == []


def test_install_excepthook_replaces_hook():
    error_log.install_excepthook()
    assert sys.excepthook is not sys.__excepthook__


def test_log_module_level(tmp_path):
    log_file = tmp_path / "errors.log"
    error_log.LOG = error_log.ErrorLog(log_file)
    error_log.log("module level message")
    assert any("module level message" in line for line in error_log.LOG.read())


def test_default_path_is_config_dir():
    el = error_log.ErrorLog()
    assert el._path == Path.home() / ".config" / "cast-control" / "errors.log"

def test_explicit_exception_tuple_outside_except_records_real_traceback(tmp_path):
    el = error_log.ErrorLog(tmp_path / "errors.log")
    try:
        raise RuntimeError("preserve this exception")
    except RuntimeError:
        captured = sys.exc_info()
    assert sys.exc_info() == (None, None, None)
    el.add("uncaught", exc_info=captured)
    text = "\n".join(el.read())
    assert "RuntimeError: preserve this exception" in text
    assert "Traceback (most recent call last)" in text
    assert "NoneType: None" not in text


def test_previous_hooks_run_exactly_once_when_log_storage_fails(tmp_path):
    old_sys, old_thread, old_log = (
        sys.excepthook, threading.excepthook, error_log.LOG,
    )
    main_next, thread_next = mock.Mock(), mock.Mock()
    sys.excepthook = main_next
    threading.excepthook = thread_next
    error_log.LOG = error_log.ErrorLog(tmp_path / "errors.log")
    try:
        error_log.install_excepthook()
        try:
            raise ValueError("do not hide me")
        except ValueError:
            captured = sys.exc_info()
        args = SimpleNamespace(
            exc_type=captured[0], exc_value=captured[1],
            exc_traceback=captured[2], thread=threading.current_thread(),
        )
        with mock.patch.object(error_log.LOG, "_persist",
                               side_effect=OSError("disk full")):
            sys.excepthook(*captured)
            threading.excepthook(args)
        main_next.assert_called_once_with(*captured)
        thread_next.assert_called_once_with(args)
        # Keyboard interrupts must go straight to the previous handlers.
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        main_next.assert_called_with(KeyboardInterrupt, mock.ANY, None)
        assert main_next.call_count == 2
    finally:
        sys.excepthook = old_sys
        threading.excepthook = old_thread
        error_log.LOG = old_log


def test_uncaught_thread_hook_logs_explicit_traceback_outside_except(tmp_path):
    old_sys, old_thread, old_log = (
        sys.excepthook, threading.excepthook, error_log.LOG,
    )
    next_hook = mock.Mock()
    threading.excepthook = next_hook
    error_log.LOG = error_log.ErrorLog(tmp_path / "errors.log")
    try:
        error_log.install_excepthook()
        try:
            raise LookupError("thread sample")
        except LookupError:
            captured = sys.exc_info()
        args = SimpleNamespace(
            exc_type=captured[0], exc_value=captured[1],
            exc_traceback=captured[2], thread=threading.current_thread(),
        )
        threading.excepthook(args)
        next_hook.assert_called_once_with(args)
        text = "\n".join(error_log.LOG.read())
        assert "LookupError: thread sample" in text
        assert "Traceback" in text
    finally:
        sys.excepthook = old_sys
        threading.excepthook = old_thread
        error_log.LOG = old_log

