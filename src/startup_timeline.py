"""Startup timeline: where the first second goes (issue #463).

Marks are first-write-wins, in milliseconds since this module was first
imported (the first line of the GUI entry module, so it excludes ~30 ms of
interpreter boot). ``interactive`` is the first idle main-loop iteration after
the first GTK paint completes. Stdlib only; safe to call from any thread.
"""
from __future__ import annotations

import threading
import time

BUDGET_MS = 800.0
_T0 = time.monotonic()
_marks: dict[str, float] = {}
_lock = threading.Lock()


def mark(name: str) -> None:
    """Record ``name`` once; later calls for the same name are ignored."""
    with _lock:
        _marks.setdefault(name, (time.monotonic() - _T0) * 1000.0)


def mark_idle() -> bool:
    """GLib idle callback: the main loop is idle after the first paint."""
    mark("interactive")
    return False


def snapshot() -> dict:
    """Marks in order, plus the interactive time against the budget (None until reached)."""
    with _lock:
        marks = {name: round(ms, 1) for name, ms in sorted(_marks.items(), key=lambda kv: kv[1])}
    interactive = marks.get("interactive")
    return {"marks_ms": marks, "budget_ms": BUDGET_MS,
            "within_budget": None if interactive is None else interactive <= BUDGET_MS}


def reset() -> None:
    """Forget all marks (tests only)."""
    with _lock:
        _marks.clear()
