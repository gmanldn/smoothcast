"""Executable URL-cast ownership regressions; no GTK or Cast device.

P1 SC-071 #80: a URL cast is ours until another app replaces it. The sleep
timer must stop our exact stream and leave a replacement playing, and a
successful handoff must release local audio.
"""
from __future__ import annotations

import textwrap
import time
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
import castctl
import idle_slate
import playback_state
import streamer
import url_control

URL = "https://example.test/film.mp4"
OTHER = "https://other.test/elsewhere.mp4"


def extracted(*names, async_runs):
    code = "class Methods:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(main_window_methods()[name]), "    ")
        for name in names
    )
    namespace = {
        "streamer": streamer,
        "playback_state": playback_state,
        "castctl": castctl,
        "idle_slate": idle_slate,
        "url_control": url_control,
        "time": time,
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None, **_kwargs:
                                 async_runs.append((work, done, failed))),
        "save_config": lambda _cfg: None,
    }
    exec(compile(code, "<url-cast-handlers>", "exec"), namespace)
    return namespace["Methods"]


def window(*names):
    jobs = []
    Methods = extracted(*names, async_runs=jobs)

    class Window(Methods):
        def __init__(self):
            self.cfg = {"device": "TV", "sleep_timer_deadline": 0.0,
                        "sleep_timer_minutes": 0}
            self.session = None
            self.busy = False
            self.external = False
            self._url_cast_url = None
            self._url_cast_seen = False
            self._cast_starting = False
            self.media = None
            self.now_playing = None
            self._finished_handled = False
            self._preview_path = None
            self.device_state = "PLAYING"
            self.device_info = None
            self.queue = []
            self.tracker = mock.Mock()
            self.np_title = mock.Mock()
            self.local_playback = mock.Mock()
            for name in ("_refresh_controls", "_poll_device", "_stop_monitor",
                         "_unload_local_video", "_console", "toast",
                         "_cast_failed"):
                setattr(self, name, mock.Mock())

        def _device(self):
            return self.cfg["device"]

        def _dlna_renderer(self, _device=None):
            return None

    return Window(), jobs


def test_url_cast_matches_requires_exact_active_content():
    assert playback_state.url_cast_matches(
        {"player_state": "PLAYING", "content_id": URL}, URL)
    assert playback_state.url_cast_matches(
        {"player_state": "PAUSED", "content_id": URL}, URL)
    assert not playback_state.url_cast_matches(
        {"player_state": "IDLE", "content_id": URL}, URL)
    assert not playback_state.url_cast_matches(
        {"player_state": "PLAYING", "content_id": OTHER}, URL)
    assert not playback_state.url_cast_matches(None, URL)
    assert not playback_state.url_cast_matches(
        {"player_state": "PLAYING", "content_id": URL}, "")


def test_successful_url_cast_records_ownership_and_stops_local_audio():
    w, jobs = window("_cast_remote_url")
    with mock.patch.object(castctl, "command", return_value=(True, "ok")):
        w._cast_remote_url(URL)
        work, done, _ = jobs.pop()
        assert work() == (True, "ok")
        done((True, "ok"))
    assert w._url_cast_url == URL
    assert w._url_cast_seen is False
    assert w.external is True
    w._unload_local_video.assert_called_once()
    w.local_playback.stop.assert_called_once()


def test_failed_url_cast_does_not_claim_ownership():
    w, jobs = window("_cast_remote_url")
    with mock.patch.object(castctl, "command", return_value=(False, "nope")):
        w._cast_remote_url(URL)
        work, done, _ = jobs.pop()
        done(work())
    assert w._url_cast_url is None
    w._cast_failed.assert_called_once()
    w.local_playback.stop.assert_not_called()


def test_sleep_timer_stops_our_url_cast():
    w, jobs = window("_sleep_tick", "_sleep_stop_url_cast")
    w._url_cast_url = URL
    w.cfg["sleep_timer_deadline"] = 1.0
    with mock.patch.object(playback_state, "timer_expired", return_value=True), \
         mock.patch.object(castctl, "info", return_value={
             "player_state": "PLAYING", "content_id": URL}), \
         mock.patch.object(castctl, "stop", return_value=(True, "stopped")) as stop:
        assert w._sleep_tick() is True
        work, done, _ = jobs.pop()
        assert work() is True
        stop.assert_called_once_with("TV")
        done(True)
    assert w._url_cast_url is None
    assert w.external is False


def test_sleep_timer_leaves_a_replacement_playing():
    w, jobs = window("_sleep_tick", "_sleep_stop_url_cast")
    w._url_cast_url = URL
    w.cfg["sleep_timer_deadline"] = 1.0
    with mock.patch.object(playback_state, "timer_expired", return_value=True), \
         mock.patch.object(castctl, "info", return_value={
             "player_state": "PLAYING", "content_id": OTHER}), \
         mock.patch.object(castctl, "stop", return_value=(True, "stopped")) as stop:
        assert w._sleep_tick() is True
        work, done, _ = jobs.pop()
        assert work() is False
        stop.assert_not_called()
        done(False)
    assert w._url_cast_url is None