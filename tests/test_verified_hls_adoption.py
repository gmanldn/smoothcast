"""Executable receiver-ownership regressions; no GTK or actual Cast device.

P0 SC-058: treat saved sessions as untrusted until an exact receiver stream
identity and completed local HLS are confirmed. Stop must not hit other media.
"""
from __future__ import annotations

import pathlib
import textwrap
import time
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
import castctl
import playback_state
import reliability_metrics
import streamer

URL = "http://192.168.1.10:8767/movie.m3u8"
GOOD = {"player_state": "PLAYING", "content_id": URL, "title": "Film"}
OTHER = {"player_state": "PLAYING", "content_id":
         "http://192.168.1.10:8767/other.m3u8", "title": "Other"}


def extracted(*names, async_runs):
    code = "class Methods:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(main_window_methods()[name]), "    ")
        for name in names
    )
    namespace = {
        "streamer": streamer,
        "playback_state": playback_state,
        "castctl": castctl,
        "reliability_metrics": reliability_metrics,
        "pathlib": pathlib,
        "time": time,
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None, **_kwargs:
                                 async_runs.append((work, done, failed))),
        "save_config": lambda _cfg: None,
    }
    exec(compile(code, "<hls-adoption-handlers>", "exec"), namespace)
    return namespace["Methods"]


def saved_state():
    return streamer.SessionState(
        file="/film.mkv", mode="transcode", offset=35.0, duration=200.0,
        device="TV", title="Film", stream_url=URL, started_at=time.time()-5,
    )


class PendingSession:
    def __init__(self, *, recoverable=True):
        self.state = None
        self.recoverable = recoverable
        self.stop = mock.Mock(side_effect=lambda _device, *, send_stop=True: bool(send_stop))

    def restore(self, state):
        self.state = state

    @property
    def mode(self):
        return self.state.mode

    def active(self):
        return False  # encoder has exited

    def recoverable_hls(self):
        return self.recoverable


def window(*names):
    queued = []
    Methods = extracted(*names, async_runs=queued)
    class Window(Methods):
        def __init__(self):
            self.cfg = {"device": "TV"}
            self.session = None
            self.busy = False
            self.external = False
            self._cast_starting = False
            self._closing = False
            self._dlna_cancel = None
            self._preview_path = None
            self.device_state = "PLAYING"
            self.device_info = None
            self.media = None
            self.queue = []
            self.tracker = mock.Mock()
            self.tracker.value.return_value = None
            for name in ("_refresh_controls", "_poll_device", "_rebuild_queue",
                         "_start_monitor", "_set_levels_hint",
                         "_set_now_playing_labels", "_stop_monitor",
                         "_console", "toast", "_cast_failed", "_record_watch"):
                setattr(self, name, mock.Mock())
            self._finished_handled = False
            self._join_slate_showing = lambda _info: False  # idle slate is not user playback (#420)

        def _device(self):
            return self.cfg["device"]

        def _dlna_renderer(self, _device=None):
            return None

    return Window(), queued


def test_completed_hls_is_not_published_until_worker_proves_ownership():
    w, jobs = window("_adopt_session")
    candidate = PendingSession()
    media = SimpleNamespace(path=pathlib.Path("/film.mkv"), duration=200.0)
    with mock.patch.object(streamer, "load_session", return_value=saved_state()), \
         mock.patch.object(streamer, "Session", return_value=candidate), \
         mock.patch.object(streamer, "ffprobe", return_value=media), \
         mock.patch.object(castctl, "info", return_value=GOOD):
        w._adopt_session()
        assert w.session is None
        assert w.queue == []
        assert not w.tracker.start.called
        assert len(jobs) == 1
        work, done, _ = jobs.pop()
        answer = work()
        assert w.session is None  # even a completed worker doesn't own the TV
        done(answer)
    assert w.session is candidate
    assert w.external is False
    assert w.now_playing == "/film.mkv"
    assert w.queue == ["/film.mkv"]
    w.tracker.start.assert_called()
    w._start_monitor.assert_called_once()


def test_other_content_on_same_hls_port_is_never_adopted():
    w, jobs = window("_adopt_session")
    candidate = PendingSession()
    with mock.patch.object(streamer, "load_session", return_value=saved_state()), \
         mock.patch.object(streamer, "Session", return_value=candidate), \
         mock.patch.object(streamer, "clear_session") as clear, \
         mock.patch.object(castctl, "info", return_value=OTHER), \
         mock.patch.object(streamer, "ffprobe") as probe:
        w._adopt_session()
        work, done, _ = jobs.pop()
        done(work())
    assert w.session is None
    assert w.queue == []
    assert not w.tracker.start.called
    probe.assert_not_called()
    clear.assert_called_once()


def test_missing_hls_segments_cannot_claim_matching_receiver():
    w, jobs = window("_adopt_session")
    with mock.patch.object(streamer, "load_session", return_value=saved_state()), \
         mock.patch.object(streamer, "Session", return_value=PendingSession(recoverable=False)), \
         mock.patch.object(castctl, "info", return_value=GOOD), \
         mock.patch.object(streamer, "ffprobe") as probe:
        w._adopt_session()
        work, done, _ = jobs.pop()
        done(work())
    assert w.session is None
    probe.assert_not_called()


def test_inflight_recovery_cannot_overwrite_new_cast_or_changed_target():
    for interruption in ("cast", "busy", "close", "target"):
        w, jobs = window("_adopt_session")
        media = SimpleNamespace(path=pathlib.Path("/film.mkv"), duration=200.0)
        with mock.patch.object(streamer, "load_session", return_value=saved_state()), \
             mock.patch.object(streamer, "Session", return_value=PendingSession()), \
             mock.patch.object(castctl, "info", return_value=GOOD), \
             mock.patch.object(streamer, "ffprobe", return_value=media):
            w._adopt_session()
            work, done, _ = jobs.pop()
            result = work()
            if interruption == "cast":
                replacement = object()
                w.session = replacement
            elif interruption == "busy":
                w.busy = True
            elif interruption == "close":
                w._closing = True
            else:
                w.cfg["device"] = "Another TV"
            done(result)
        assert w.session is (replacement if interruption == "cast" else None)
        assert not w.tracker.start.called


def test_unavailable_receiver_does_not_discard_saved_session():
    w, jobs = window("_adopt_session")
    with mock.patch.object(streamer, "load_session", return_value=saved_state()), \
         mock.patch.object(streamer, "Session", return_value=PendingSession()), \
         mock.patch.object(castctl, "info", return_value=None), \
         mock.patch.object(streamer, "clear_session") as clear:
        w._adopt_session()
        work, done, _ = jobs.pop()
        done(work())
    assert w.session is None
    clear.assert_not_called()


def test_external_detector_requires_exact_saved_url_even_when_encoder_alive():
    w, _ = window("_detect_external")
    w.session = PendingSession()
    w.session.restore(saved_state())
    for info, is_external in ((GOOD, False), (OTHER, True)):
        w.device_info = info
        w.device_state = "PLAYING"
        w._detect_external()
        assert w.external is is_external


def test_stop_rechecks_receiver_identity_before_sending_remote_stop():
    for info, expected in ((GOOD, True), (OTHER, False), (None, False)):
        w, jobs = window("stop_stream")
        w.session = PendingSession()
        w.session.restore(saved_state())
        with mock.patch.object(castctl, "info", return_value=info), \
             mock.patch.object(castctl, "stop") as stop_other:
            w.stop_stream()
            work, done, _ = jobs.pop()
            sent = work()
            done(sent)
        assert sent is expected
        w._console.assert_called()
        # session.stop handles own process cleanup; no direct fallback Stop.
        stop_other.assert_not_called()
