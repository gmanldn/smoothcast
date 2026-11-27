"""State-based action availability (#458): one rule for the desktop and the web.

The web remote must not depend on the desktop's GTK widget sensitivity, so both
surfaces derive play/pause, stop and volume availability from controller state
through ``action_state``. These tests pin the pure predicates and guard the two
call sites from drifting back to widget sensitivity.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import action_state  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _session(state=object()):
    return SimpleNamespace(state=state)


def test_receiver_online_only_offline_is_unavailable():
    assert action_state.receiver_online("PLAYING")
    assert action_state.receiver_online("IDLE")
    assert not action_state.receiver_online("OFFLINE")


def test_playback_active_tracks_session_state_and_external_casts():
    assert not action_state.playback_active(None, False)
    assert not action_state.playback_active(_session(None), False)
    assert action_state.playback_active(_session(), False)
    assert action_state.playback_active(None, True)


def test_local_preview_ready_needs_a_path_and_no_receiver_owner():
    assert action_state.local_preview_ready("/films/a.mkv", None, False)
    assert not action_state.local_preview_ready(None, None, False)
    assert not action_state.local_preview_ready("/films/a.mkv", _session(), False)
    assert not action_state.local_preview_ready("/films/a.mkv", None, True)


def test_can_play_pause_requires_an_online_active_or_local_preview_and_idle():
    assert action_state.can_play_pause("PLAYING", _session(), False, None, False)
    assert action_state.can_play_pause("PLAYING", None, False, "/a.mkv", False)
    # A local preview works even with the receiver offline.
    assert action_state.can_play_pause("OFFLINE", None, False, "/a.mkv", False)
    # Offline receiver with no local preview cannot be played.
    assert not action_state.can_play_pause("OFFLINE", _session(), False, None, False)
    # A live external cast still counts even when the receiver reports idle.
    assert action_state.can_play_pause("IDLE", None, True, None, False)
    # Busy always blocks a new transport command.
    assert not action_state.can_play_pause("PLAYING", _session(), False, None, True)


def test_can_stop_matches_play_except_a_cancellable_busy_dlna_setup():
    assert action_state.can_stop("PLAYING", _session(), False, None, False, None)
    assert not action_state.can_stop("OFFLINE", _session(), False, None, False, None)
    # During a DLNA setup the desktop can still cancel, so stop stays available.
    assert action_state.can_stop("PLAYING", _session(), False, None, True, object())
    assert not action_state.can_stop("PLAYING", _session(), False, None, True, None)


def test_can_volume_needs_an_online_controllable_receiver():
    assert action_state.can_volume("PLAYING", True)
    assert not action_state.can_volume("OFFLINE", True)
    assert not action_state.can_volume("PLAYING", False)


def test_can_seek_needs_a_live_known_duration_stream():
    assert action_state.can_seek(_session(), False, True, False, 120)
    assert not action_state.can_seek(None, False, True, False, 120)
    assert not action_state.can_seek(_session(), True, True, False, 120)
    assert not action_state.can_seek(_session(), False, False, False, 120)
    assert not action_state.can_seek(_session(), False, True, True, 120)
    assert not action_state.can_seek(_session(), False, True, False, 0)
