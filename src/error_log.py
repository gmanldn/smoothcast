"""Bounded, append-efficient application-wide error log.

Normal entries append exactly once. Oversized logs compact atomically to a
bounded recent tail; loading a huge old log never reads its entire history.
Safe to call from any thread and does not import or launch GTK.
"""
from __future__ import annotations

from collections import deque
import paths
import datetime as _dt
import os
import pathlib
import sys
import threading
import traceback
from types import TracebackType
from typing import Optional

import command_trace
import log_jsonl

ExceptionDetails = tuple[type[BaseException], BaseException, TracebackType | None]

MAX_LINES = 10000
# Hysteresis: compact at 4 MiB, retaining at most 2 MiB so a sustained
# failure burst amortises the occasional full rewrite rather than writing
# 10,000 lines for every new error.
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_RETAIN_BYTES = 2 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024
FILENAME = "errors.log"
# Opt-in machine-readable mode: SMOOTHCAST_LOG_FORMAT=jsonl writes one JSON object per entry.
FORMAT_ENV = "SMOOTHCAST_LOG_FORMAT"


class ErrorLog:
    def __init__(self, path: Optional[pathlib.Path | str] = None) -> None:
        if path is None:
            path = paths.config_dir() / FILENAME
        self._path = pathlib.Path(path)
        self._lock = threading.Lock()
        self._lines: deque[str] = deque()
        self._retained_bytes = 0
        self._disk_size = 0
        self._loaded = False
        self._ensure_parent()

    def _ensure_parent(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @staticmethod
    def _bytes(line: str) -> int:
        return len(line.encode("utf-8")) + 1

    def _retain(self, entry: str) -> None:
        self._lines.append(entry)
        self._retained_bytes += self._bytes(entry)
        while self._lines and (
            len(self._lines) > MAX_LINES or self._retained_bytes > MAX_RETAIN_BYTES
        ):
            dropped = self._lines.popleft()
            self._retained_bytes -= self._bytes(dropped)

    def _load(self) -> None:
        # Existing log files may be gigabytes (historically no file-byte cap).
        # Seek from the end and read at most MAX_LOG_BYTES; discard any partial
        # leading line. This bounds startup I/O and memory independent of size.
        self._lines.clear()
        self._retained_bytes = 0
        self._disk_size = 0
        try:
            with self._path.open("rb") as fh:
                self._disk_size = fh.seek(0, 2)
                offset = max(0, self._disk_size - MAX_LOG_BYTES)
                fh.seek(offset)
                tail = fh.read(MAX_LOG_BYTES)
            if offset:
                first_newline = tail.find(b"\n")
                tail = tail[first_newline + 1:] if first_newline >= 0 else b""
            for line in tail.decode("utf-8", "replace").splitlines():
                if line.strip():
                    self._retain(line)
        except OSError:
            self._lines.clear()
            self._retained_bytes = self._disk_size = 0
        self._loaded = True

    def _persist(self) -> None:
        """Atomically compact the recent tail (also used for clear)."""
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as fh:
                for line in self._lines:
                    fh.write(line + "\n")
            tmp.replace(self._path)
            self._disk_size = self._retained_bytes
        finally:
            # Atomic replacement never leaves a stale partial temporary file.
            tmp.unlink(missing_ok=True)

    def _append(self, entry: str) -> None:
        """One append per error; only compact after exceeding the byte limit."""
        with self._path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(entry + "\n")
        self._disk_size += self._bytes(entry)
        if self._disk_size > MAX_LOG_BYTES:
            self._persist()

    def add(self, message: str, *, exc_info: bool | ExceptionDetails = False) -> None:
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        trace_id = command_trace.current_id()
        if trace_id is not None:
            message = f"[command:{trace_id}] {message}"
        if exc_info:
            # Uncaught exception hooks run outside an except block: sys.exc_info()
            # is empty there. The explicit tuple is the authoritative traceback.
            details = exc_info if isinstance(exc_info, tuple) else sys.exc_info()
            detail = "".join(traceback.format_exception(*details))
            message = f"{message}\n{detail}"
        if os.environ.get(FORMAT_ENV, "").strip().lower() == "jsonl":
            entry = log_jsonl.entry(stamp, message, trace_id, bool(exc_info), MAX_ENTRY_BYTES)
        else:
            entry = f"{stamp}  {message}"
        encoded = entry.encode("utf-8")
        if len(encoded) > MAX_ENTRY_BYTES:
            marker = b"\n[... oversized entry truncated ...]\n"
            head = MAX_ENTRY_BYTES * 3 // 4
            tail = MAX_ENTRY_BYTES - head - len(marker)
            # Keep both the initial failure context and final traceback cause.
            entry = (encoded[:head].decode("utf-8", "ignore")
                     + marker.decode("ascii")
                     + encoded[-tail:].decode("utf-8", "ignore"))
        with self._lock:
            if not self._loaded:
                self._load()
            self._retain(entry)
            self._append(entry)

    def read(self) -> list[str]:
        with self._lock:
            if not self._loaded:
                self._load()
            return list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._retained_bytes = 0
            self._loaded = True
            self._persist()


LOG = ErrorLog()


def log(message: str, *, exc_info: bool | ExceptionDetails = False) -> None:
    LOG.add(message, exc_info=exc_info)


def install_excepthook() -> None:
    """Redirect uncaught exceptions (main + background threads) into the log."""
    previous_hook = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            previous_hook(exc_type, exc_value, exc_tb)
            return
        try:
            log("uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        except Exception:  # noqa: BLE001 - logging is best-effort; the original traceback still reaches stderr
            # Logging is best-effort; preserve the original traceback at stderr
            # even with a full disk, bad permissions or a broken log backend.
            pass
        finally:
            previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook

    previous_thread_hook = threading.excepthook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is KeyboardInterrupt:
            previous_thread_hook(args)
            return
        try:
            log("uncaught thread exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        except Exception:  # noqa: BLE001 - logging is best-effort; the previous hook still runs
            pass
        finally:
            previous_thread_hook(args)

    threading.excepthook = thread_hook
