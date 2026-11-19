"""Executable restart regressions for settings source and pause preservation.

P1 SC-074 #83 and SC-077 #86: a restart triggered by seek/speed/soundtrack must
keep a paused film paused and must apply the settings the UI says take effect on
the next (re)start. No GTK or Cast device is used.
"""
from __future__ import annotations

import pathlib
import textwrap
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from gui_source import main_window_methods
import castctl
import playback_state
import position_tracker
import streamer
import subtitle_delay
import subtitle_restart

DEFAULTS = {"audio_gain": 0.0}


def extracted(*names, async_runs, saves):
    code = "class Methods:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(main_window_methods()[name]), "    ")
        for name in names
    )
    namespace = {
        "streamer": streamer,
        "subtitle_delay": subtitle_delay,
        "subtitle_restart": subtitle_restart,
        "playback_state": playback_state,
        "castctl": castctl,
        "pathlib": pathlib,
        "time": time,
        "DEFAULTS": DEFAULTS,
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None, **_kwargs:
                                 async_runs.append((work, done, failed))),
        "save_config": lambda cfg: saves.append(dict(cfg)),
    }
    exec(compile(code, "<restart-handlers>", "exec"), namespace)
    return namespace["Methods"]


def state():
    return SimpleNamespace(
        file="/film.mkv", title="Film", quality="balanced", audio="dialogue",
        speed=1.0, rotation=0, audio_track_index=-1, burn_subs=False, subs="",
        embedded_subtitle_index=-1, audio_gain_db=3.0,
    )


def window(*names, playing=True):
    jobs, saves = [], []
    Methods = extracted(*names, async_runs=jobs, saves=saves)

    class Window(Methods):
        def __init__(self):
            self.cfg = {"quality": "high", "audio": "night", "rotation": 90,
                        "audio_gain": 6.0, "playback_speed": 1.0}
            self.session = None
            self.media = None
            self.busy = False
            self.device_state = "PLAYING"
            self.tracker = position_tracker.PositionTracker()
            self.tracker.start(10.0, 200.0, playing)
            if "_restart_at" not in names:
                self._restart_at = mock.Mock()
            for name in ("_update_audio_choices", "_start_monitor",
                         "_set_levels_hint", "_refresh_controls", "_poll_device",
                         "_cast_failed", "toast"):
                setattr(self, name, mock.Mock())

        def _device(self):
            return "TV"

        def _device_host(self, _device):
            return "192.168.1.10"

    return Window(), jobs, saves


def run_restart(w, session, *, paused):
    w.device_state = "PAUSED" if paused else "PLAYING"
    w.tracker.start(10.0, 200.0, not paused)
    media = SimpleNamespace(path=pathlib.Path("/film.mkv"), duration=200.0)
    with mock.patch.object(streamer, "ffprobe", return_value=media), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(castctl, "pause", return_value=(True, "")) as pause:
        w._restart_at(session, 42.0)
        work, done, _ = w.jobs.pop()
        result = work()
        done(result)
    return pause


def test_restart_applies_current_preferences_not_stale_session_settings():
    w, jobs, _ = window("_restart_at")
    w.jobs = jobs
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    run_restart(w, session, paused=False)
    kwargs = session.start_transcode.call_args.kwargs
    # The settings card promises these apply on the next (re)start.
    assert kwargs["quality"] == "high"
    assert kwargs["audio_profile"] == "night"
    assert kwargs["rotation"] == 90
    assert kwargs["audio_gain_db"] == 6.0
    assert kwargs["audio_track_index"] == -1


def test_paused_restart_seeks_and_stays_paused():
    w, jobs, _ = window("_restart_at")
    w.jobs = jobs
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    pause = run_restart(w, session, paused=True)
    pause.assert_called_once_with("TV")
    assert w.tracker.playing is False
    assert w.tracker.known is True
    # A paused restart without a fresh device poll must not extrapolate time.
    assert w.tracker.value(now=w.tracker._epoch + 90.0) == 42.0


def test_recovery_after_long_pause_restores_play_and_two_x_source_clock():
    w, jobs, _ = window("_restart_at")
    w.device_state = "PAUSED"
    w.tracker.start(10.0, 200.0, False)
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    session.state.speed = 2.0
    media = SimpleNamespace(path=pathlib.Path("/film.mkv"), duration=200.0)
    with mock.patch.object(streamer, "ffprobe", return_value=media), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(castctl, "pause", return_value=(True, "")) as pause:
        w._restart_at(session, 42.0, resume_after_pause=True)
        work, done, _ = jobs.pop()
        done(work())
    pause.assert_not_called()
    assert session.start_transcode.call_args.kwargs["speed"] == 2.0
    assert w.tracker.playing is True
    # 42 s + 5 s of wall clock at 2x. Float rounding depends on the magnitude
    # of the monotonic clock (51.99999999999997 on one CI runner), so compare
    # with a tolerance rather than bit-exactly.
    assert w.tracker.value(now=w.tracker._epoch + 5.0) == pytest.approx(52.0)


def test_playing_restart_stays_playing():
    w, jobs, _ = window("_restart_at")
    w.jobs = jobs
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    pause = run_restart(w, session, paused=False)
    pause.assert_not_called()
    assert w.tracker.playing is True


def test_restart_uses_requested_speed_override():
    w, jobs, _ = window("_restart_at")
    w.jobs = jobs
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    media = SimpleNamespace(path=pathlib.Path("/film.mkv"), duration=200.0)
    with mock.patch.object(streamer, "ffprobe", return_value=media), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(castctl, "pause", return_value=(True, "")):
        w._restart_at(session, 42.0, speed_override=2.5)
        work, done, _ = jobs.pop()
        done(work())
    assert session.start_transcode.call_args.kwargs["speed"] == 2.5


def test_rejected_live_speed_change_is_not_saved():
    w, jobs, saves = window("_set_speed")
    w.session = mock.Mock()
    w.session.state = state()
    w.busy = True
    w._set_speed(2.0)
    assert w.cfg["playback_speed"] == 1.0
    assert saves == []
    w._restart_at.assert_not_called()

    w.busy = False
    w._set_speed(2.0)
    assert w.cfg["playback_speed"] == 2.0
    assert saves and saves[-1]["playback_speed"] == 2.0
    w._restart_at.assert_called_once()