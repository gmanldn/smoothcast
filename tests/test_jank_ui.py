"""Headless tests for the GLib scheduling around the jank detector (#442)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import jank_ui  # noqa: E402
import jank_watchdog  # noqa: E402


class FakeWatchdog:
    def __init__(self, lag_ms: float = 300.0) -> None:
        self.beats = 0
        self._stalls = [jank_watchdog.Stall(at=1.0, lag_ms=lag_ms, stack=())]

    def beat(self) -> None:
        self.beats += 1

    def poll(self):
        return self._stalls.pop(0) if self._stalls else None


def _monitor(**overrides):
    scheduled: list[tuple[int, object]] = []
    removed: list[int] = []
    monitor = jank_ui.JankMonitor(
        watchdog=overrides.pop("watchdog", FakeWatchdog()),
        timeout_add=lambda ms, fn: (scheduled.append((ms, fn)), 7)[1],
        source_remove=lambda source: removed.append(source),
        **overrides)
    return monitor, scheduled, removed


def test_start_schedules_the_beat_and_installs_the_registry():
    monitor, scheduled, _ = _monitor()
    try:
        monitor.start()
        assert scheduled and scheduled[0][0] == jank_ui.BEAT_MS
        assert jank_watchdog.current() is monitor.watchdog
        assert scheduled[0][1]() is True
        assert monitor.watchdog.beats == 1
    finally:
        monitor.stop()


def test_the_monitor_thread_records_stalls_and_stop_clears_everything():
    monitor, scheduled, removed = _monitor(poll_ms=5)
    try:
        monitor.start()
        deadline = time.monotonic() + 2.0
        while monitor.max_lag_ms == 0.0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert monitor.max_lag_ms == 300.0
        assert monitor.smoke_stall() is True
    finally:
        monitor.stop()
    assert removed == [7]
    assert jank_watchdog.current() is None
    assert scheduled[0][1]() is False


def test_a_stall_below_the_smoke_limit_is_not_a_smoke_stall():
    monitor, _, _ = _monitor(watchdog=FakeWatchdog(lag_ms=120.0), poll_ms=5)
    try:
        monitor.start()
        deadline = time.monotonic() + 2.0
        while monitor.max_lag_ms == 0.0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert monitor.max_lag_ms == 120.0
        assert monitor.smoke_stall() is False
    finally:
        monitor.stop()


def test_stop_is_idempotent_even_when_glib_already_dropped_the_source():
    monitor, _, _ = _monitor()
    monitor.start()
    monitor._source_remove = lambda source: (_ for _ in ()).throw(RuntimeError("gone"))
    monitor.stop()
    monitor.stop()
    assert jank_watchdog.current() is None
