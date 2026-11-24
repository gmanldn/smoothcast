"""Tests for src/error_log.py ring-buffer error logger."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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
        with mock.patch.object(error_log.LOG, "_append",
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



def test_oversized_existing_log_loads_bounded_tail_and_compacts(tmp_path):
    path = tmp_path / "errors.log"
    # Simulate the old logger having grown far beyond the new size bound.
    with path.open("wb") as fh:
        fh.write(b"stale entry\n" * 700000)
        fh.write(b"newest preserved traceback: ValueError: boom\n")
    size_before = path.stat().st_size
    assert size_before > error_log.MAX_LOG_BYTES
    logger = error_log.ErrorLog(path)
    assert any("ValueError: boom" in row for row in logger.read())
    assert logger._retained_bytes <= error_log.MAX_RETAIN_BYTES
    assert len(logger.read()) <= error_log.MAX_LINES
    logger.add("current failure")
    assert path.stat().st_size <= error_log.MAX_RETAIN_BYTES
    restored = error_log.ErrorLog(path)
    assert any("ValueError: boom" in row for row in restored.read())
    assert restored.read()[-1].endswith("current failure")


def test_burst_is_append_only_and_compacts_infrequently(tmp_path):
    path = tmp_path / "errors.log"
    logger = error_log.ErrorLog(path)
    with mock.patch.object(error_log, "MAX_LOG_BYTES", 1024), \
         mock.patch.object(error_log, "MAX_RETAIN_BYTES", 512), \
         mock.patch.object(error_log, "MAX_ENTRY_BYTES", 256), \
         mock.patch.object(logger, "_persist", wraps=logger._persist) as compaction:
        for index in range(1000):
            logger.add(f"burst {index}: " + "x" * 55)
            assert path.stat().st_size <= 1024
            assert logger._disk_size == path.stat().st_size
        assert compaction.call_count < 160, "full history rewritten too frequently"
        assert logger.read()[-1].endswith("x" * 55)
        assert len(logger.read()) < 20
        assert logger._retained_bytes <= 512


def test_large_multiline_traceback_keeps_beginning_and_final_cause(tmp_path):
    path = tmp_path / "errors.log"
    logger = error_log.ErrorLog(path)
    details = "first failure context\n" + ("frame: xxxxxxxxxxxxxxxxxxx\n" * 5000)
    details += "last important cause: RuntimeError: final error"
    logger.add(details)
    assert path.stat().st_size <= error_log.MAX_ENTRY_BYTES + 8
    assert logger._disk_size == path.stat().st_size
    restored = error_log.ErrorLog(path)
    saved = "\n".join(restored.read())
    assert "first failure context" in saved
    assert "RuntimeError: final error" in saved
    assert "oversized entry truncated" in saved


def test_clear_after_reopening_is_atomic_and_stays_empty(tmp_path):
    path = tmp_path / "errors.log"
    path.write_text("old\nnew\n", encoding="utf-8")
    logger = error_log.ErrorLog(path)
    assert logger.read() == ["old", "new"]
    logger.clear()
    assert path.read_bytes() == b""
    assert error_log.ErrorLog(path).read() == []
    logger.add("fresh")
    assert "old" not in path.read_text()
    assert "fresh" in path.read_text()


def test_jsonl_mode_writes_one_valid_object_per_entry(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("SMOOTHCAST_LOG_FORMAT", "jsonl")
    log = error_log.ErrorLog(tmp_path / "errors.log")
    log.add("plain failure with é and \"quotes\"")
    try:
        raise ValueError("boom")
    except ValueError:
        log.add("handler failed", exc_info=True)
    lines = (tmp_path / "errors.log").read_text("utf-8").splitlines()
    assert len(lines) == 2                       # the traceback is a field, not extra lines
    first, second = (json.loads(line) for line in lines)
    assert first["msg"] == 'plain failure with é and "quotes"' and first["level"] == "error"
    assert "traceback" not in first and first["ts"]
    assert second["msg"] == "handler failed" and "ValueError: boom" in second["traceback"]
    assert [json.loads(line)["msg"] for line in log.read()] == [first["msg"], second["msg"]]


def test_jsonl_mode_stays_valid_and_bounded_for_huge_or_hostile_entries(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("SMOOTHCAST_LOG_FORMAT", "JSONL")
    log = error_log.ErrorLog(tmp_path / "errors.log")
    log.add("é" * 40000 + "\n" + "\x00\n\t" * 5000)
    log.add("x" * 100000)
    for line in (tmp_path / "errors.log").read_text("utf-8").splitlines():
        assert len(line.encode("utf-8")) <= error_log.MAX_ENTRY_BYTES
        assert json.loads(line)["level"] == "error"


def test_default_format_is_unchanged_plain_text(tmp_path, monkeypatch):
    monkeypatch.delenv("SMOOTHCAST_LOG_FORMAT", raising=False)
    log = error_log.ErrorLog(tmp_path / "errors.log")
    log.add("hello")
    assert (tmp_path / "errors.log").read_text("utf-8").rstrip().endswith("  hello")


def test_unknown_format_value_falls_back_to_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOOTHCAST_LOG_FORMAT", "xml")
    log = error_log.ErrorLog(tmp_path / "errors.log")
    log.add("hello")
    assert not (tmp_path / "errors.log").read_text("utf-8").startswith("{")
