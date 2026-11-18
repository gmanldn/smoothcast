"""Unit tests for pure-logic modules (no GTK/display/device required)."""

import math
import sys
from pathlib import Path

import pytest

import castctl
import audio_monitor
import streamer
import cast_control


# ── castctl.fmt_time ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "seconds,expected",
    [
        (None, "--:--"),
        (0, "00:00"),
        (5, "00:05"),
        (59, "00:59"),
        (60, "01:00"),
        (61, "01:01"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (3600 * 5 + 30, "5:00:30"),
    ],
)
def test_fmt_time(seconds, expected):
    assert castctl.fmt_time(seconds) == expected


# ── castctl.volume_percent ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ({}, None),
        ({"volume_level": 0.5}, 50),
        ({"volume_level": 1.0}, 100),
        ({"volume_level": 0.0}, 0),
        ({"volume_level": 0.25}, 25),
        ({"volume_level": 50}, 50),
        ({"volume_level": 100}, 100),
        ({"volume_level": "0.75"}, 75),
        ({"volume_level": "abc"}, None),
    ],
)
def test_volume_percent(raw, expected):
    assert castctl.volume_percent(raw) == expected


# ── castctl.player_state / is_playing / is_seekable ────────────────────────

def test_player_state_none():
    assert castctl.player_state(None) == "OFFLINE"
    # empty dict is falsy too; a real IDLE dict has player_state
    assert castctl.player_state({}) == "OFFLINE"
    assert castctl.player_state({"player_state": "IDLE"}) == "IDLE"
    assert castctl.player_state({"player_state": "playing"}) == "PLAYING"


@pytest.mark.parametrize(
    "state,playing",
    [
        ("PLAYING", True),
        ("BUFFERING", True),
        ("PAUSED", False),
        ("IDLE", False),
        ("OFFLINE", False),
    ],
)
def test_is_playing(state, playing):
    info = {"player_state": state} if state != "OFFLINE" else None
    assert castctl.is_playing(info) is playing


def test_is_seekable():
    assert castctl.is_seekable(None) is False
    assert castctl.is_seekable({}) is False
    assert castctl.is_seekable({"duration": 100, "current_time": 10}) is True
    assert castctl.is_seekable({"duration": 100, "current_time": None}) is False


# ── cast_control.pretty_title ──────────────────────────────────────────────

class _FakePath:
    def __init__(self, name):
        self.stem = name
        self.name = name


def test_pretty_title_strips_dots_and_year():
    assert cast_control.pretty_title(_FakePath("Show.Name.S01E02")) == "Show Name S01E02"
    assert cast_control.pretty_title(_FakePath("Movie.2023")) == "Movie"
    assert cast_control.pretty_title(_FakePath("Movie 2023")) == "Movie"
    assert cast_control.pretty_title(_FakePath("NoYearHere")) == "NoYearHere"
    assert cast_control.pretty_title(_FakePath("...only.dots...")) == "only dots"


# ── audio_monitor._db ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("-23.5", -23.5),
        ("0", 0.0),
        ("-60", -60.0),
        ("-inf", audio_monitor.FLOOR_DB),
        ("nan", audio_monitor.FLOOR_DB),
        ("abc", audio_monitor.FLOOR_DB),
        (None, audio_monitor.FLOOR_DB),
        ("inf", 0.0),
        ("-70", audio_monitor.FLOOR_DB),  # below floor clamps
    ],
)
def test_db(raw, expected):
    result = audio_monitor._db(raw)
    if expected != expected:  # nan
        assert math.isnan(result)
    else:
        assert result == expected


# ── audio_monitor.LevelSample.gain_db ──────────────────────────────────────

def test_level_sample_gain_db():
    s = audio_monitor.LevelSample(
        in_rms=-30.0, out_rms=-20.0,
        in_peak=-10.0, out_peak=-5.0,
        in_l=-30.0, in_r=-30.0,
        out_l=-20.0, out_r=-20.0,
    )
    assert s.gain_db == 10.0

    s2 = audio_monitor.LevelSample(
        in_rms=-10.0, out_rms=-15.0,
        in_peak=-5.0, out_peak=-10.0,
        in_l=-10.0, in_r=-10.0,
        out_l=-15.0, out_r=-15.0,
    )
    assert s2.gain_db == -5.0


# ── streamer.audio_filters ─────────────────────────────────────────────────

def test_audio_filters_original():
    assert streamer.audio_filters("original") == []
    assert streamer.audio_filters("original", 10.0) == []


def test_audio_filters_dialogue_no_gain():
    assert streamer.audio_filters("dialogue") == [
        "acompressor=threshold=0.06:ratio=8:attack=20:release=250:makeup=1.8",
        "alimiter=limit=0.95:attack=5:release=80",
    ]


def test_audio_filters_dialogue_with_gain():
    result = streamer.audio_filters("dialogue", 6.0)
    assert result[0] == "volume=6dB"
    assert result[1:] == streamer.AUDIO_FILTERS["dialogue"]


def test_audio_filters_zero_or_negative_gain_skips_volume():
    assert streamer.audio_filters("dialogue", 0.0) == streamer.AUDIO_FILTERS["dialogue"]
    assert streamer.audio_filters("dialogue", -3.0) == streamer.AUDIO_FILTERS["dialogue"]
    assert streamer.audio_filters("dialogue", None) == streamer.AUDIO_FILTERS["dialogue"]


def test_audio_filters_night():
    result = streamer.audio_filters("night", 2.0)
    assert result[0] == "volume=2dB"
    assert result[1:] == streamer.AUDIO_FILTERS["night"]


def test_audio_filters_unknown_profile():
    assert streamer.audio_filters("nope") == []
    assert streamer.audio_filters("nope", 5.0) == []


# ── streamer.effective_chain ───────────────────────────────────────────────

def test_effective_chain_original_is_empty(monkeypatch):
    monkeypatch.setattr(streamer, "measure_mean_volume", lambda path, max_seconds=60: None)
    assert streamer.effective_chain("any/file.mp4", "original") == []


def test_effective_chain_applies_trim_plus_manual(monkeypatch):
    monkeypatch.setattr(
        streamer, "measure_mean_volume", lambda path, max_seconds=60: -30.0
    )
    # target -16, mean -30 -> trim = 14, manual 0 -> effective 14
    result = streamer.effective_chain("any/file.mp4", "dialogue", manual_gain_db=0.0)
    assert result[0] == "volume=14dB"


# ── PositionTracker ────────────────────────────────────────────────────────

def test_position_tracker_unknown_returns_none():
    t = cast_control.PositionTracker()
    assert t.value() is None


def test_position_tracker_basic_advance(monkeypatch):
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.start(0.0, 100.0, playing=True)
    assert t.value() == 0.0
    now[0] += 7.5
    assert t.value() == 7.5

    # duration clamp
    t.start(99.0, 100.0, playing=True)
    now[0] += 5.0
    assert t.value() == 100.0


def test_position_tracker_pause_resume_accumulates(monkeypatch):
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.start(0.0, 100.0, playing=True)
    now[0] += 10.0
    assert t.value() == 10.0  # 10s played

    t.set_state(False)  # pause at t=1010
    now[0] += 5.0
    assert t.value() == 10.0  # paused: no advance

    t.set_state(True)  # resume at t=1015
    now[0] += 5.0
    assert t.value() == 15.0  # 10s played + 5s after resume


def test_position_tracker_paused_does_not_drift_on_device_update(monkeypatch):
    """device_update while paused must not make the position creep forward."""
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.start(0.0, 100.0, playing=True)
    t.set_state(False)  # pause at t=1000, position 0

    # Device reports position 0 at t=1000 while paused.
    t.device_update(0.0, 100.0)
    now[0] += 4.0  # 4s later, still paused
    assert t.value() == 0.0  # paused: no drift

    # Device still at 0 at t=1004 while paused.
    t.device_update(0.0, 100.0)
    now[0] += 4.0
    assert t.value() == 0.0  # still paused: no drift


def test_position_tracker_device_update_advances_when_playing(monkeypatch):
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.start(0.0, 100.0, playing=True)  # mark as playing
    t.device_update(10.0, 100.0)  # device at 10s
    now[0] += 3.0
    assert t.value() == 13.0  # playing: advances from device position

    # Fresh device report rebases.
    t.device_update(20.0, 100.0)
    now[0] += 2.0
    assert t.value() == 22.0


def test_position_tracker_device_update_paused_stays_static(monkeypatch):
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.device_update(10.0, 100.0)
    t.set_state(False)  # pause
    now[0] += 5.0
    assert t.value() == 10.0  # paused: holds device position

    t.set_state(True)  # resume
    now[0] += 5.0
    assert t.value() == 20.0  # advances from paused device position


def test_position_tracker_estimated_mode_unaffected(monkeypatch):
    """start() (no device position) keeps the old estimated behaviour."""
    t = cast_control.PositionTracker()
    now = [1000.0]
    monkeypatch.setattr(cast_control.time, "monotonic", lambda: now[0])

    t.start(0.0, 100.0, playing=True)
    now[0] += 7.5
    assert t.value() == 7.5  # estimated: advances from base

    t.set_state(False)
    now[0] += 4.0
    assert t.value() == 7.5  # paused: holds

