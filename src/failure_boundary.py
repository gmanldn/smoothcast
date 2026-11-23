"""Civil, bounded, GTK-free description of unexpected failures (issue #512).

SmoothCast never shows a raw traceback and never fails silently. Anything that
escapes a handler is turned into one short, polite message for the user; the
technical detail goes only to the private error log, with paths redacted.

``describe`` never raises. ``Notifier`` stops a failure that repeats from
flooding the interface (same failure at most once per ``repeat`` seconds, at
most ``per_window`` distinct failures per ``window`` seconds).
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time
from typing import Callable

TITLE = "SmoothCast hit an unexpected problem"
STEPS = ("Retry the action.", "If it keeps happening, use Report a problem in the Help menu.")
CODE = "unexpected_error"
MAX_MESSAGE = 220
MAX_DETAIL = 400
MAX_KEYS = 64

_POSIX_PATH = re.compile(r"(?<![\w.])/(?:[^\s:'\"<>|]+/)*([^\s:'\"<>|/]+)")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\s:'\"<>|\\]+\\)*([^\s:'\"<>|\\]+)")


def redact(text: str) -> str:
    """Replace absolute paths with ``.../name`` and the home directory with ``~``."""
    try:
        home = os.path.expanduser("~")
        if home and home not in ("~", "/"):
            text = text.replace(home, "~")
        text = _WINDOWS_PATH.sub(lambda m: f".../{m.group(1)}", text)
        return _POSIX_PATH.sub(lambda m: f".../{m.group(1)}", text)
    except Exception:
        return ""


@dataclass(frozen=True)
class UserFailure:
    title: str
    steps: tuple[str, ...]
    detail: str  # private: for the error log and diagnostics, never for display
    reviewed: bool = False  # title is audited copy that already includes the first step

    @property
    def message(self) -> str:
        """One display-safe message: what happened and the first thing to try."""
        if self.reviewed:
            return self.title[:MAX_MESSAGE]
        head = self.title.rstrip(".")
        text = f"{head}. {self.steps[0]}" if self.steps else f"{head}."
        return text[:MAX_MESSAGE]

    @property
    def key(self) -> str:
        return f"{self.title}|{self.detail.split(':', 1)[0]}"


def _detail(exc: object) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: object = exc
    while current is not None and id(current) not in seen and len(parts) < 4:
        seen.add(id(current))
        try:
            text = str(current)
        except Exception:
            text = ""
        name = type(current).__name__
        parts.append(f"{name}: {redact(text)}" if text else name)
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return " <- ".join(parts)[:MAX_DETAIL]


def describe(exc: object) -> UserFailure:
    """Map any exception (or nothing) to a polite failure; never raises."""
    try:
        reviewed = getattr(exc, "user_message", None)
        if isinstance(reviewed, str) and reviewed.strip():
            steps = getattr(exc, "steps", ())
            clean = tuple(s for s in steps if isinstance(s, str)) if isinstance(steps, tuple) else ()
            return UserFailure(reviewed.strip()[:MAX_MESSAGE], clean, _detail(exc), True)
        return UserFailure(TITLE, STEPS, _detail(exc))
    except Exception:
        return UserFailure(TITLE, STEPS, "")


class Notifier:
    """Rate limiter so one repeating fault cannot flood toasts or logs."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 repeat: float = 30.0, window: float = 60.0, per_window: int = 3) -> None:
        self._clock = clock
        self._repeat = repeat
        self._window = window
        self._per_window = per_window
        self._last: dict[str, float] = {}
        self._recent: list[float] = []

    def allow(self, failure: UserFailure) -> bool:
        now = self._clock()
        self._recent = [t for t in self._recent if now - t < self._window]
        last = self._last.get(failure.key)
        if last is not None and now - last < self._repeat:
            return False
        if len(self._recent) >= self._per_window:
            return False
        if len(self._last) >= MAX_KEYS:
            oldest = min(self._last, key=self._last.__getitem__)
            self._last.pop(oldest, None)
        self._last[failure.key] = now
        self._recent.append(now)
        return True
