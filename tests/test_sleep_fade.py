"""Sleep-timer volume fade (issue #270): GTK-free, no receiver, injected I/O."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import config_control
import sleep_fade as sf


class Rig:
    """Fake receiver; commands run synchronously through the injected runner."""

    def __init__(self, volume=60, fail_sets=0):
        self.volume, self.sets, self.reads = volume, [], 0
        self.fail_sets = fail_sets
        self.fader = sf.SleepFader(self.read, self.set, self.run)

    def read(self, device):
        self.reads += 1
        return self.volume

    def set(self, device, pct):
        self.sets.append((device, pct))
        if self.fail_sets > 0:
            self.fail_sets -= 1
            return False
        self.volume = pct
        return True

    @staticmethod
    def run(work, done):
        done(work())

    def tick(self, now, deadline=1000.0, fade=30, device="TV", active=True):
        self.fader.tick(now=now, deadline=deadline, fade_seconds=fade,
                        device=device, active=active)


def test_fade_level_is_linear_bounded_and_safe():
    assert sf.fade_level(60, 30, 30) == 60
    assert sf.fade_level(60, 15, 30) == 30
    assert sf.fade_level(60, 0, 30) == 0
    assert sf.fade_level(60, -5, 30) == 0
    assert sf.fade_level(60, 99, 30) == 60
    assert sf.fade_level(60, 10, 0) == 60


@pytest.mark.parametrize("good", [0, 1, 30, 600])
def test_valid_seconds_accepts_bounded_ints(good):
    assert sf.valid_seconds(good) == good


@pytest.mark.parametrize("bad", [-1, 601, 1.5, "30", None, True])
def test_valid_seconds_rejects_everything_else(bad):
    assert sf.valid_seconds(bad) is None


def test_setting_default_and_validation():
    defaults = {"sleep_fade_seconds": 30}
    for good in (0, 45, 600):
        assert config_control.sanitise_config({"sleep_fade_seconds": good}, defaults)["sleep_fade_seconds"] == good
    for bad in (-1, 601, "5", 2.5, True):
        assert config_control.sanitise_config({"sleep_fade_seconds": bad}, defaults)["sleep_fade_seconds"] == 30


def test_nothing_happens_outside_the_fade_window_or_when_disabled():
    r = Rig()
    r.tick(900)                      # 100 s before deadline, fade is 30 s
    r.tick(980, fade=0)              # fade disabled
    r.tick(980, deadline=0)          # no timer armed
    r.tick(980, active=False)        # nothing playing
    r.tick(980, device="")           # no device
    assert r.reads == 0 and r.sets == []


def test_fades_down_then_restores_after_the_cast_stops():
    r = Rig(volume=60)
    r.tick(975)                      # enters window: read once, start fading
    r.tick(978)
    r.tick(990)
    r.tick(996)
    levels = [pct for _, pct in r.sets]
    assert r.reads == 1
    assert levels == sorted(levels, reverse=True) and levels[-1] < levels[0] < 60
    assert r.volume == levels[-1]
    # Deadline passes: app clears the timer and starts stopping the cast.
    r.tick(1001, deadline=0.0, active=True)
    assert r.fader.phase == "await_stop" and r.volume == levels[-1]   # not restored while playing
    r.tick(1004, deadline=0.0, active=False)
    assert r.sets[-1] == ("TV", 60) and r.volume == 60
    assert r.fader.phase is None


def test_cancelling_the_timer_restores_immediately():
    r = Rig(volume=40)
    r.tick(975)
    r.tick(985)
    assert r.volume < 40
    r.tick(986, deadline=0.0, active=True)   # cancelled well before the deadline
    assert r.volume == 40 and r.fader.phase is None


def test_rearming_for_later_restores_and_can_fade_again():
    r = Rig(volume=50)
    r.tick(975)
    r.tick(985)
    r.tick(986, deadline=5000.0)
    assert r.volume == 50
    r.tick(4980, deadline=5000.0)
    assert r.reads == 2 and r.fader.phase == "fading"


def test_changing_device_never_touches_the_new_receiver():
    r = Rig(volume=50)
    r.tick(975)
    sets_before = len(r.sets)
    r.tick(985, device="Bedroom")
    assert len(r.sets) == sets_before and r.fader.phase is None


def test_unreadable_or_silent_volume_is_left_alone_and_not_retried():
    for volume in (None, 0):
        r = Rig(volume=volume)
        r.tick(975)
        r.tick(978)
        r.tick(990)
        assert r.sets == [] and r.reads == 1 and r.fader.phase is None


def test_cast_that_never_stops_is_restored_after_the_wait_limit():
    r = Rig(volume=60)
    r.tick(975)
    r.tick(996)
    r.tick(1001, deadline=0.0, active=True)
    r.tick(1000 + sf.RESTORE_MAX_WAIT - 1, deadline=0.0, active=True)
    assert r.fader.phase == "await_stop"
    r.tick(1000 + sf.RESTORE_MAX_WAIT + 1, deadline=0.0, active=True)
    assert r.volume == 60


def test_failed_restore_is_retried_a_bounded_number_of_times():
    r = Rig(volume=60)
    r.tick(975)
    r.tick(996)
    r.fail_sets = 2
    r.tick(1001, deadline=0.0, active=False)
    r.tick(1004, deadline=0.0, active=False)
    r.tick(1007, deadline=0.0, active=False)
    assert r.volume == 60 and r.fader.phase is None
    r2 = Rig(volume=60)
    r2.tick(975)
    r2.fail_sets = 99
    for t in range(1001, 1030, 3):
        r2.tick(t, deadline=0.0, active=False)
    assert r2.fader.phase is None   # gave up after RESTORE_ATTEMPTS


def test_overlapping_commands_are_never_issued():
    queued = []
    r = Rig(volume=60)
    r.fader = sf.SleepFader(r.read, r.set, lambda work, done: queued.append((work, done)))
    r.tick(975)
    r.tick(976)   # read still in flight
    assert len(queued) == 1
    work, done = queued.pop()
    done(work())
    r.tick(977)
    assert len(queued) == 1   # exactly one set in flight


def test_garbage_deadline_values_are_ignored():
    r = Rig()
    for bad in (None, "x", float("nan"), -5):
        r.tick(975, deadline=bad)
    assert r.reads == 0


def test_window_wiring_uses_the_fader_and_a_timer():
    text = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert "sleep_fade.make_fader(Async.run)" in text
    timers = (ROOT / "src" / "cast_ui_timers.py").read_text(encoding="utf-8")
    assert 'w._set_ui_timer("fade", schedule.fade_ms, w._scheduled_fade_tick)' in timers
    assert "def _sleep_fade_tick" in (ROOT / "src" / "cast_settings.py").read_text(encoding="utf-8")
    assert '"sleep_fade_seconds": 30' in (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
