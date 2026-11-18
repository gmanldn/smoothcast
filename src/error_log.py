"""Application-wide ring-buffer error log.

All runtime errors are appended to ``errors.log`` (gitignored) kept at most
``MAX_LINES`` entries; oldest entries are dropped once the cap is reached so
the file behaves as a ring buffer. Safe to call from any thread.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys
import threading
import traceback
from types import TracebackType
from typing import Optional

ExceptionDetails = tuple[type[BaseException], BaseException, TracebackType | None]

MAX_LINES = 10000
FILENAME = "errors.log"


class ErrorLog:
    def __init__(self, path: Optional[pathlib.Path | str] = None) -> None:
        if path is None:
            path = pathlib.Path.home() / ".config" / "cast-control" / FILENAME
        self._path = pathlib.Path(path)
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._loaded = False
        self._ensure_parent()

    def _ensure_parent(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _load(self) -> None:
        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as fh:
                self._lines = [line.rstrip("\n") for line in fh if line.strip()]
        except OSError:
            self._lines = []
        self._lines = self._lines[-MAX_LINES:]
        self._loaded = True

    def _persist(self) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for line in self._lines:
                fh.write(line + "\n")
        tmp.replace(self._path)

    def add(self, message: str, *, exc_info: bool | ExceptionDetails = False) -> None:
        stamp = _dt.datetime.now().isoformat(timespec="seconds")
        if exc_info:
            # Uncaught exception hooks run outside an except block: sys.exc_info()
            # is empty there. The explicit tuple is the authoritative traceback.
            details = exc_info if isinstance(exc_info, tuple) else sys.exc_info()
            detail = "".join(traceback.format_exception(*details))
            message = f"{message}\n{detail}"
        entry = f"{stamp}  {message}"
        with self._lock:
            if not self._loaded:
                self._load()
            self._lines.append(entry)
            if len(self._lines) > MAX_LINES:
                self._lines = self._lines[-MAX_LINES:]
            self._persist()

    def read(self) -> list[str]:
        with self._lock:
            if not self._loaded:
                self._load()
            return list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines = []
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
        except Exception:
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
        except Exception:
            pass
        finally:
            previous_thread_hook(args)

    threading.excepthook = thread_hook
