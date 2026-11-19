"""P0 SC-009: executable transport-command serialization regressions.

GTK-free: extract real UI method bodies and run with fake receivers/Async
callbacks. These tests never spawn GTK, FFmpeg or real network commands.
"""
from __future__ import annotations

import pathlib
import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
import hls_pause_recovery


def fixture(mode="direct", *, paused=False):
    methods = main_window_methods()
    source = "class Transport:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[name]), "    ")
        for name in ("toggle_play", "seek_to")
    )
    jobs = []
    cast = mock.Mock()
    cast.is_seekable.return_value = True
    cast.play.return_value = (True, "")
    cast.pause.return_value = (True, "")
    cast.seek.return_value = (True, "")
    dlna = mock.Mock()
    namespace = {
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **_kwargs: jobs.append((work, done, failed))
        ),
        "castctl": cast,
        "hls_pause_recovery": hls_pause_recovery,
        "dlna": dlna,
        "pathlib": pathlib,
        "fmt_time": lambda seconds: str(int(seconds)),
    }
    exec(compile(source, "<transport-serialization>", "exec"), namespace)

    class Window(namespace["Transport"]):
        def __init__(self):
            self.busy = False
            self._closing = False
            self.external = False
            self.device_state = "PAUSED" if paused else "PLAYING"
            self.session = SimpleNamespace(mode=mode, state=SimpleNamespace(file="/film.mkv", device="TV A"))
            self.tracker = mock.Mock()
            self.tracker.duration = 120.0
            self.media = None
            self.device_info = {"player_state": self.device_state}
            self.seekbar = mock.Mock()
            self.seekbar.buffered = 0.0
            self._preview_path = None
            self.queue_durations = {}
            self.now_playing = "/film.mkv"
            self._preview_position = 0.0
            self._current_device = "TV A"
            self._refresh_controls = mock.Mock()
            self._poll_device = mock.Mock()
            self._resume_monitor = mock.Mock()
            self._stop_monitor = mock.Mock()
            self.toast = mock.Mock()
            self._restart_at = mock.Mock()
            self._toggle_local_preview = mock.Mock()
            self._cast_path = mock.Mock()
            self._queue_preview = mock.Mock()

        def _device(self):
            return self._current_device

        def _dlna_renderer(self, device=None):
            return SimpleNamespace(key="renderer A") if mode == "dlna" else None

        def _local_stream(self):
            return None

    return Window(), jobs, cast, dlna


def run_job(jobs):
    work, done, failed = jobs.pop(0)
    try:
        value = work()
    except Exception as exc:
        if failed:
            failed(str(exc))
        return
    if done:
        done(value)


def test_pause_is_single_flight_and_only_updates_tracker_on_success():
    window, jobs, cast, _ = fixture()
    window.toggle_play()
    assert window.busy is True
    window.toggle_play()
    window.seek_to(25)
    assert len(jobs) == 1
    assert not window.seekbar.set_state.called
    window.tracker.set_state.assert_not_called()
    run_job(jobs)
    cast.pause.assert_called_once_with("TV A")
    assert window.busy is False
    window.tracker.set_state.assert_called_once_with(False)
    window._stop_monitor.assert_called_once_with(reset=False)
    window._poll_device.assert_called_once()


def test_play_failure_never_falsely_updates_tracker_or_monitor():
    window, jobs, cast, _ = fixture(paused=True)
    cast.play.return_value = (False, "Rejected by receiver")
    window.toggle_play()
    run_job(jobs)
    assert window.busy is False
    window.tracker.set_state.assert_not_called()
    window._resume_monitor.assert_not_called()
    window.toast.assert_called_with("Rejected by receiver", error=True)
    window._poll_device.assert_called_once()


def test_dlna_pause_exception_is_reported_and_releases_lock():
    window, jobs, _, dlna = fixture(mode="dlna")
    dlna.pause.side_effect = RuntimeError("Network down")
    window.toggle_play()
    run_job(jobs)
    assert window.busy is False
    assert "Network down" in window.toast.call_args.args[0]
    window.tracker.set_state.assert_not_called()
    window._poll_device.assert_called_once()


def test_long_paused_hls_rebuilds_from_frozen_source_time_at_one_and_two_x():
    for speed, position in ((1.0, 42.125), (2.0, 91.25)):
        window, jobs, cast, _ = fixture(mode="transcode", paused=True)
        window.external = False
        window.tracker.known = True
        window.tracker.playing = False
        window.tracker.paused_for.return_value = 35.0
        window.tracker.value.return_value = position
        window.session.state.speed = speed
        window.toggle_play()
        assert window.busy
        assert jobs == []  # no stale castctl.play against deleted HLS segments
        cast.play.assert_not_called()
        window._restart_at.assert_called_once_with(
            window.session, position, resume_after_pause=True,
        )
        window.toggle_play()
        window._restart_at.assert_called_once()


def test_short_or_unknown_hls_pause_preserves_normal_receiver_resume():
    for pause_age, position in ((4.0, 40.0), (60.0, None)):
        window, jobs, cast, _ = fixture(mode="transcode", paused=True)
        window.tracker.known = True
        window.tracker.playing = False
        window.tracker.paused_for.return_value = pause_age
        window.tracker.value.return_value = position
        window.toggle_play()
        window._restart_at.assert_not_called()
        assert len(jobs) == 1
        run_job(jobs)
        cast.play.assert_called_once_with("TV A")
        window.tracker.set_state.assert_called_once_with(True)


def test_long_pause_does_not_restart_nonowned_or_noncast_stream():
    for mode, owner in (("dlna", "TV A"), ("direct", "TV A"), ("transcode", "TV B")):
        window, jobs, _, _ = fixture(mode=mode, paused=True)
        window.session.state.device = owner
        window.tracker.known = True
        window.tracker.playing = False
        window.tracker.paused_for.return_value = 100.0
        window.tracker.value.return_value = 42.0
        window.toggle_play()
        window._restart_at.assert_not_called()
        assert len(jobs) == 1


def test_direct_seek_is_single_flight_and_success_resyncs():
    window, jobs, cast, _ = fixture()
    window.seek_to(35)
    assert window.busy is True
    window.seek_to(80)
    window.toggle_play()
    assert len(jobs) == 1
    window.seekbar.set_state.assert_called_once_with(35, 120, 0.0)
    run_job(jobs)
    cast.seek.assert_called_once_with("TV A", 35)
    assert window.busy is False
    window._poll_device.assert_called_once()
    assert window.toast.call_args.args[0].startswith("Jumped to ")


def test_direct_seek_rejection_releases_lock_and_resyncs():
    window, jobs, cast, _ = fixture()
    cast.seek.return_value = (False, "Not seekable")
    window.seek_to(44)
    run_job(jobs)
    assert window.busy is False
    window.toast.assert_called_with("Not seekable", error=True)
    window._poll_device.assert_called_once()


def test_dlna_seek_exception_releases_lock_and_resyncs():
    window, jobs, _, dlna = fixture(mode="dlna")
    dlna.seek.side_effect = OSError("TV disconnected")
    window.seek_to(42)
    assert window.busy
    run_job(jobs)
    assert not window.busy
    assert "TV disconnected" in window.toast.call_args.args[0]
    window._poll_device.assert_called_once()


def test_stale_callbacks_never_modify_a_replaced_session_or_device():
    for operation in ("toggle_play", "seek_to"):
        for replacement in ("device", "session", "closing"):
            window, jobs, _, _ = fixture()
            if operation == "toggle_play":
                window.toggle_play()
            else:
                window.seek_to(18)
            if replacement == "device":
                window._current_device = "TV B"
            elif replacement == "session":
                window.session = object()
            else:
                window._closing = True
            run_job(jobs)
            window.tracker.set_state.assert_not_called()
            window._poll_device.assert_not_called()
            # The retired command must not unlock a newer operation.
            assert window.busy


def test_transcode_seek_still_routes_through_hls_restart_once():
    window, jobs, _, _ = fixture(mode="transcode")
    window.seek_to(38)
    assert not jobs
    assert window.busy
    window._restart_at.assert_called_once_with(window.session, 38)
    window.seek_to(39)
    window._restart_at.assert_called_once()


def test_local_preview_still_seeks_without_remote_command():
    window, jobs, _, _ = fixture()
    window.session = None
    window._preview_path = "/film.mkv"
    window.seek_to(30)
    assert not jobs
    assert window._preview_position == 30
    window._queue_preview.assert_called_once_with(30)
    assert not window.busy
