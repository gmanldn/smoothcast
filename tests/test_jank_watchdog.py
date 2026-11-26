"""Fake-clock tests for the main-loop jank detector core (#442)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import jank_watchdog  # noqa: E402
from jank_watchdog import JankWatchdog, scrub_frames  # noqa: E402


def test_no_stall_below_the_threshold():
    dog = JankWatchdog(threshold_ms=100.0)
    dog.beat(0.0)
    assert dog.poll(0.050) is None
    assert dog.count == 0
    assert dog.samples == ()
    assert dog.p99_ms == 0.0
    assert dog.stats() == {"stalls": 0, "p99_ms": 0.0, "last_lag_ms": 0.0,
                          "threshold_ms": 100.0}


def test_a_stall_counts_once_per_rate_limit_window():
    dog = JankWatchdog(threshold_ms=100.0, rate_limit_s=1.0)
    dog.beat(0.0)
    stall = dog.poll(0.250)
    assert stall is not None and stall.lag_ms == pytest.approx(250.0)
    assert dog.count == 1
    # The loop has not recovered, but the detector must not spam the log.
    assert dog.poll(0.400) is None
    assert dog.count == 1
    assert dog.poll(1.400) is not None
    assert dog.count == 2


def test_stack_samples_are_scrubbed_and_kept_bounded():
    home = "/home/guest"
    frames = [f'File "{home}/media/film.mkv"',
              "cast_ui.py:120 in _on_click session=9d5f0c1b2a3e4f5d6a7b8c9d0e1f2a3b"]
    dog = JankWatchdog(threshold_ms=100.0, rate_limit_s=0.0, max_samples=2,
                       capture_stack=lambda: frames, home=home)
    dog.beat(0.0)
    first = dog.poll(0.200)
    assert first.stack == ('File "~/media/film.mkv"',
                           "cast_ui.py:120 in _on_click session=<id>")
    for moment in (1.0, 2.0):
        dog.beat(moment)
        dog.poll(moment + 0.2)
    assert dog.count == 3
    assert len(dog.samples) == 2


def test_a_failing_capturer_never_breaks_the_detector():
    def boom():
        raise RuntimeError("frame walk failed")

    dog = JankWatchdog(threshold_ms=100.0, capture_stack=boom)
    dog.beat(0.0)
    stall = dog.poll(0.500)
    assert stall is not None and stall.stack == () and dog.count == 1


def test_p99_uses_nearest_rank_on_a_known_series():
    dog = JankWatchdog(threshold_ms=1.0, rate_limit_s=0.0, max_samples=100)
    for lag_ms in range(1, 101):
        dog.beat(0.0)
        dog.poll(lag_ms / 1000.0)
    assert dog.count == 100
    assert dog.p99_ms == pytest.approx(99.0)
    assert dog.stats()["last_lag_ms"] == pytest.approx(100.0)


def test_reset_rearms_without_losing_the_count():
    dog = JankWatchdog(threshold_ms=100.0, rate_limit_s=0.0)
    dog.beat(0.0)
    dog.poll(0.5)
    dog.reset()
    assert dog.samples == () and dog.p99_ms == 0.0
    assert dog.count == 1


def test_scrub_frames_replaces_home_and_opaque_ids():
    assert scrub_frames(["/home/guest/a/b"], home="/home/guest") == ("~/a/b",)
    assert scrub_frames(["id 00112233445566778899aabbccddeeff"]) == ("id <id>",)


def test_importing_the_detector_pulls_in_no_gtk():
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import jank_watchdog; "
         "assert 'gi' not in sys.modules, sorted(sys.modules)" % str(ROOT / "src")],
        capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr


def test_install_registry_round_trip():
    dog = JankWatchdog()
    assert jank_watchdog.current() is None
    try:
        assert jank_watchdog.install(dog) is None
        assert jank_watchdog.current() is dog
        assert jank_watchdog.install(None) is dog
        assert jank_watchdog.current() is None
    finally:
        jank_watchdog.install(None)


def test_on_stall_callback_runs_and_cannot_break_poll():
    seen = []

    def record(stall):
        seen.append(stall)
        raise RuntimeError("counter is broken")

    dog = JankWatchdog(threshold_ms=100.0, on_stall=record)
    dog.beat(0.0)
    stall = dog.poll(0.400)
    assert stall is not None and seen == [stall] and dog.count == 1


def test_diagnostics_summary_is_disabled_when_unwired():
    jank_watchdog.install(None)
    assert jank_watchdog.diagnostics_summary() == {
        "enabled": False, "stalls": 0, "p99_ms": 0.0, "last_lag_ms": 0.0,
        "threshold_ms": jank_watchdog.DEFAULT_THRESHOLD_MS}
    dog = JankWatchdog(threshold_ms=100.0)
    dog.beat(0.0)
    dog.poll(0.300)
    try:
        jank_watchdog.install(dog)
        assert jank_watchdog.diagnostics_summary() == {
            "enabled": True, "stalls": 1, "p99_ms": 300.0, "last_lag_ms": 300.0,
            "threshold_ms": 100.0}
    finally:
        jank_watchdog.install(None)
