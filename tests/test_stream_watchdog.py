"""P0 #17: deterministic, GTK-free playback stall and retry tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
import progress_model
import stream_watchdog


def observe(w, now, *, session=None, epoch=1, state="PLAYING",
            owned=True, busy=False, encoded=10.0, received=5.0,
            done=False, remaining=100.0):
    if session is None:
        session = "movie A"
    return w.observe(
        session=session, epoch=epoch, now=now,
        receiver_state=state, owned=owned, busy=busy,
        encoder_seconds=encoded, receiver_seconds=received,
        encoder_done=done, seconds_remaining=remaining,
    )


def test_encoder_stall_restarts_once_and_stays_bounded_across_generation():
    w = stream_watchdog.StreamWatchdog(encoder_timeout=20, receiver_timeout=35)
    assert observe(w, 0) is None
    assert observe(w, 10, encoded=11, received=6) is None
    assert observe(w, 29, encoded=11, received=9) is None
    assert observe(w, 30, encoded=11, received=9) == "encoder_stalled"
    assert w.restarts == 1
    # A restart produces a new FFmpeg timeline but not a new movie/session.
    assert observe(w, 31, epoch=2, encoded=0, received=0) is None
    assert observe(w, 52, epoch=2, encoded=0, received=2) == "recovery_exhausted"
    assert observe(w, 70, epoch=2, encoded=0, received=2) is None
    # Switching films resets the allowance.
    assert observe(w, 71, session="movie B", encoded=1, received=1) is None
    assert w.restarts == 0
    assert observe(w, 95, session="movie B", encoded=1, received=1) == "encoder_stalled"


def test_receiver_stall_only_when_encoder_advances_and_ownership_confirmed():
    w = stream_watchdog.StreamWatchdog(encoder_timeout=20, receiver_timeout=35)
    assert observe(w, 0, encoded=4, received=8) is None
    assert observe(w, 20, encoded=24, received=8) is None
    assert observe(w, 36, encoded=40, received=8) == "receiver_stalled"
    assert w.restarts == 1
    missing = stream_watchdog.StreamWatchdog(encoder_timeout=20, receiver_timeout=35)
    assert observe(missing, 0, encoded=None, received=8) is None
    assert observe(missing, 60, encoded=None, received=8) is None
    assert missing.restarts == 0


def test_paused_busy_foreign_offline_and_finished_never_restart():
    gates = (
        {"state": "PAUSED"},
        {"state": "OFFLINE"},
        {"state": "IDLE"},
        {"owned": False},
        {"busy": True},
        {"done": True},
        {"remaining": 3},
    )
    for gate in gates:
        w = stream_watchdog.StreamWatchdog(encoder_timeout=20)
        assert observe(w, 0) is None
        assert observe(w, 100, **gate) is None, gate
        assert w.restarts == 0, gate
        # An ownership/pause transition must not immediately consume retry.
        assert observe(w, 101) is None, gate
    w = stream_watchdog.StreamWatchdog(encoder_timeout=20)
    assert observe(w, 0) is None
    assert w.observe(session=None, epoch=None, now=100,
                     receiver_state="IDLE", owned=False, busy=False,
                     encoder_seconds=None, receiver_seconds=None) is None
    assert w.restarts == 0


def test_invalid_or_backward_progress_never_misdiagnosed_as_starvation():
    w = stream_watchdog.StreamWatchdog(encoder_timeout=20, receiver_timeout=35)
    assert observe(w, 0, encoded=float("nan"), received=float("nan")) is None
    assert observe(w, 50, encoded=float("inf"), received=-5) is None
    assert w.restarts == 0
    assert observe(w, 51, encoded=20, received=10) is None
    # A seek/restart resets epoch and observed clocks.
    assert observe(w, 52, epoch=2, encoded=0, received=0) is None
    assert observe(w, 60, epoch=2, encoded=1, received=2) is None


URL = "http://192.168.1.10:8767/movie.m3u8"


def fake_window():
    w = SimpleNamespace()
    state = SimpleNamespace(mode="transcode", stream_url=URL, title="Film",
                            duration=140.0, offset=0.0, started_at=42.0)
    session = SimpleNamespace(mode="transcode", state=state)
    w.session = session
    w.device_info = {"player_state": "PLAYING", "content_id": URL,
                     "title": "Film", "current_time": 6.0}
    w.device_state = "PLAYING"
    w.busy = False
    w._closing = False
    w._cast_starting = False
    w._stream_watchdog = stream_watchdog.StreamWatchdog(
        encoder_timeout=20, receiver_timeout=35
    )
    for method in ("_refresh_controls", "_restart_at", "toast", "_console"):
        setattr(w, method, mock.Mock())
    return w, session

clock = [0.0]


def test_gui_wiring_restarts_own_hls_once_at_source_clock_and_never_blocks():
    w, session = fake_window()
    with mock.patch.object(stream_watchdog.time, "monotonic", side_effect=lambda: clock[0]):
        clock[0] = 0
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8, progress="continue"), 75)
        clock[0] = 21
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8, progress="continue"), 75)
        assert w.busy
        w._restart_at.assert_called_once_with(session, 75)
        w._console.assert_called_once()
        clock[0] = 50
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8, progress="continue"), 75)
    w._restart_at.assert_called_once()



def test_gui_wiring_refuses_remote_takeover_of_unrelated_content():
    w, _ = fake_window()
    w.device_info["content_id"] = "http://192.168.1.10:8767/other.m3u8"
    with mock.patch.object(stream_watchdog.time, "monotonic", side_effect=lambda: clock[0]):
        clock[0] = 0
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8), 20)
        clock[0] = 100
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8), 20)
    w._restart_at.assert_not_called()
    assert not w.busy


def test_gui_wiring_never_restarts_completed_or_paused_movie():
    w, _ = fake_window()
    with mock.patch.object(stream_watchdog.time, "monotonic", side_effect=lambda: clock[0]):
        clock[0] = 0
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8), 20)
        w.device_state = "PAUSED"
        clock[0] = 100
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8), 20)
        w.device_state = "PLAYING"
        clock[0] = 101
        stream_watchdog.recover_window(w, progress_model.Progress(out_time=8, progress="end"), 130)
    w._restart_at.assert_not_called()


def test_existing_ui_tick_calls_watchdog_without_new_timer_or_cast():
    source = main_window_methods()["_tick"]
    assert "stream_watchdog.recover_window(self, snapshot, position)" in source
    init_source = main_window_methods()["__init__"]
    assert "self._stream_watchdog = stream_watchdog.StreamWatchdog()" in init_source
    assert "GLib.timeout_add(500, self._tick)" in init_source
