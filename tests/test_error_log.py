"""Tests for src/error_log.py ring-buffer error logger."""

import sys
import tempfile
from pathlib import Path

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
