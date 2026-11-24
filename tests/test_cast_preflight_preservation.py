"""P0 #13: early Cast errors must not disrupt the original owned stream.

GTK-free: execute real extracted GUI handlers with stubbed side effects.
No receiver/network commands or live desktop are launched.
"""
from __future__ import annotations

import pathlib

from async_jobs import UserFacingError
import textwrap
import threading
from types import SimpleNamespace
from unittest import mock

from gui_source import handler_globals, main_window_methods
import dlna
import playback_state
import queue_metadata
import reliability_metrics
import streamer
import subtitle_style
import watch_history


def window(*, device="TV", subs="auto", active=True, owner=None, dependencies=None):
    names = ("_cast_path", "_cast_preflight_failed", "stop_stream")
    methods = main_window_methods()
    source = "class Handlers:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[name]), "    ")
        for name in names
    )
    ns = {"playback_state": playback_state, "threading": threading, "pathlib": pathlib,
          "watch_history": watch_history, "queue_metadata": queue_metadata,
          "reliability_metrics": reliability_metrics,
          "hdr_tonemap": __import__("hdr_tonemap"),
          "fingerprint": __import__("fingerprint"),
          "Async": SimpleNamespace(run=lambda _work, **_kwargs: None)}
    ns.update(handler_globals())
    ns.update(dependencies or {})
    exec(compile(source, "<cast-preflight-failure>", "exec"), ns)
    previous = SimpleNamespace(
        state=SimpleNamespace(device=device if owner is None else owner),
        active=lambda: active,
    )

    class Window(ns["Handlers"]):
        def __init__(self):
            self.cfg = {"positions": {}, "subs": subs}
            self.session = previous
            self.busy = False
            self._dlna_cancel = None
            self._media_cache = {}
            self._cancel_queue_prewarm = mock.Mock()
            self._local_video_path = None
            self._preview_generation = 0
            self._preview_pending = None
            self._preview_position = 19.0
            self.local_playback = mock.Mock()
            self._unload_local_video = mock.Mock()
            self._refresh_controls = mock.Mock()
            self._cast_failed = mock.Mock()
            self._stop_monitor = mock.Mock()
            self.toast = mock.Mock()
            self._console = mock.Mock()
            self._resolve_subs = mock.Mock(return_value=None)
            self.tracker = object()

        def _device(self):
            return device

        def _dlna_renderer(self, selection):
            return None

        def _device_host(self, selection):
            return "192.168.1.41"

        def _local_stream(self):
            return None

    return Window(), previous


def test_undiscovered_dlna_does_not_stop_prior_active_cast_or_monitor():
    w, previous = window(device="DLNA · Living Room · 192.168.1.41")
    tracker = w.tracker
    reason = w._cast_path(pathlib.Path("/unavailable.mkv"), 49.0)
    assert reason == "DLNA receiver is not currently discovered; scan your network again"
    assert w.session is previous
    assert w.tracker is tracker
    w._cast_failed.assert_not_called()
    w._stop_monitor.assert_not_called()
    assert w.busy is False and w._dlna_cancel is None
    assert "DLNA receiver is not currently discovered" in w.toast.call_args.args[0]
    assert w.toast.call_args.kwargs == {"error": True}
    assert "Cast preparation failed" in w._console.call_args.args[0]
    w._refresh_controls.assert_called()


def test_missing_explicit_subtitles_preserves_position_and_old_cast():
    w, previous = window(subs="pick")
    tracker = w.tracker
    reason = w._cast_path(pathlib.Path("/another.mkv"), 33.0)
    assert reason == "Selected subtitle file is missing or unsupported; choose a valid .srt"
    w._resolve_subs.assert_called_once()
    assert w.session is previous
    assert w.tracker is tracker
    assert w._preview_position == 33.0
    w._cast_failed.assert_not_called()
    w._stop_monitor.assert_not_called()
    assert w.busy is False
    assert "subtitle file is missing" in w.toast.call_args.args[0]


def test_no_valid_predecessor_uses_normal_failure_cleanup():
    for active, owner in ((False, "TV"), (True, "Someone else")):
        w, previous = window(subs="pick", active=active, owner=owner)
        w._cast_path(pathlib.Path("/another.mkv"), 0.0)
        w._cast_failed.assert_called_once_with(
            "Selected subtitle file is missing or unsupported; choose a valid .srt"
        )
        assert w.session is previous


def test_no_previous_session_uses_normal_failure_cleanup():
    w, _ = window(subs="pick")
    w.session = None
    w._cast_path(pathlib.Path("/another.mkv"), 0.0)
    w._cast_failed.assert_called_once()

def test_incompatible_dlna_formats_preserve_previous_cast(monkeypatch):
    import audio_delay
    import subtitle_delay

    def run(work, *, done=None, failed=None, domain):
        try:
            result = work()
        except UserFacingError as exc:
            if failed is not None:
                failed(exc.user_message)
        else:
            if done is not None:
                done(result)
            else:
                raise AssertionError("incompatible cast reached playback")

    w, previous = window(device="DLNA · Living Room · 192.168.1.41", subs="off",
                         dependencies={
                             "Async": SimpleNamespace(run=run), "dlna": dlna,
                             "UserFacingError": UserFacingError,
                             "streamer": streamer, "subtitle_style": subtitle_style,
                             "audio_delay": audio_delay, "subtitle_delay": subtitle_delay,
                         })
    renderer = dlna.Renderer("Living Room", "192.168.1.41", "", "", "")
    w._dlna_renderer = mock.Mock(return_value=renderer)
    w.np_meta = mock.Mock()
    w._closing = False
    w.cfg.update(direct=True, audio="original")
    previous.stop = mock.Mock()
    monkeypatch.setattr(streamer, "ffprobe", lambda path: object())
    monkeypatch.setattr(streamer, "require_compatible_ffmpeg", lambda: None)
    monkeypatch.setattr(dlna, "advertised_http_formats", lambda target: {"video/webm"})

    w._cast_path(pathlib.Path("/new-film.mp4"), 0.0)

    previous.stop.assert_not_called()
    w._cast_failed.assert_not_called()
    assert w.session is previous
    assert not w.busy and w._dlna_cancel is None
    assert "no supported MP4 or MPEG-TS" in w.toast.call_args.args[0]


def test_stop_cancels_cast_during_probe_before_stopping_previous_session(monkeypatch):
    import audio_delay
    import subtitle_delay

    def run(work, *, done, failed, domain):
        try:
            done(work())
        except Exception as exc:
            failed(str(exc))

    w, previous = window(device="DLNA · Living Room · 192.168.1.41", subs="off",
                         dependencies={
                             "Async": SimpleNamespace(run=run), "dlna": dlna,
                             "streamer": streamer, "subtitle_style": subtitle_style,
                             "audio_delay": audio_delay, "subtitle_delay": subtitle_delay,
                         })
    renderer = dlna.Renderer("Living Room", "192.168.1.41", "", "", "")
    w._dlna_renderer = mock.Mock(return_value=renderer)
    w.np_meta = mock.Mock()
    w._closing = False
    w.cfg.update(direct=True, audio="original")
    w.tracker = mock.Mock()
    w.media = None
    previous.stop = mock.Mock()

    def probe(_path):
        w.stop_stream()
        return object()

    monkeypatch.setattr(streamer, "ffprobe", probe)
    monkeypatch.setattr(streamer, "require_compatible_ffmpeg", lambda: None)

    w._cast_path(pathlib.Path("/new-film.mp4"), 0.0)

    previous.stop.assert_not_called()
    w._cast_failed.assert_not_called()
    assert w.session is previous and not w.busy and w._dlna_cancel is None
    assert any("Cancelling cast setup" in call.args[0]
               for call in w.toast.call_args_list)


def test_stop_during_old_session_stop_aborts_new_receiver_handoff(monkeypatch):
    import audio_delay
    import subtitle_delay

    def run(work, *, done, failed, domain):
        try:
            done(work())
        except Exception as exc:
            failed(str(exc))

    w, previous = window(
        device="DLNA · Living Room · 192.168.1.41", subs="off",
        dependencies={
            "Async": SimpleNamespace(run=run), "dlna": dlna,
            "streamer": streamer, "audio_delay": audio_delay,
            "subtitle_delay": subtitle_delay, "subtitle_style": subtitle_style,
        },
    )
    renderer = dlna.Renderer("Living Room", "192.168.1.41", "", "", "")
    w._dlna_renderer = mock.Mock(return_value=renderer)
    w.np_meta = mock.Mock()
    w._closing = False
    w.cfg.update(direct=True, audio="original")
    w.tracker = mock.Mock()
    w.tracker.value.return_value = None
    w.media = None
    stopped = {"value": False}

    def stop_previous(*_args, **_kwargs):
        stopped["value"] = True
        w.stop_stream()

    previous.stop = mock.Mock(side_effect=stop_previous)
    previous.mode = "dlna"
    previous.active = lambda: not stopped["value"]
    monkeypatch.setattr(streamer, "ffprobe", lambda _path: object())
    monkeypatch.setattr(streamer, "require_compatible_ffmpeg", lambda: None)
    monkeypatch.setattr(dlna, "negotiate_media_type", lambda _renderer: "video/mp4")
    with mock.patch.object(dlna, "Session") as session:
        w._cast_path(pathlib.Path("/new-film.mp4"), 0.0)
        session.assert_not_called()
    previous.stop.assert_called_once_with(
        "DLNA · Living Room · 192.168.1.41", send_stop=True,
    )
    assert w.session is previous
    w._cast_failed.assert_called_once_with("Cast cancelled before receiver handoff")


def test_stop_during_new_session_start_stops_owned_receiver(monkeypatch):
    import audio_delay
    import subtitle_delay

    def run(work, *, done, failed, domain):
        try:
            done(work())
        except Exception as exc:
            failed(str(exc))

    w, previous = window(
        device="TV", subs="off",
        dependencies={
            "Async": SimpleNamespace(run=run), "dlna": dlna,
            "streamer": streamer, "audio_delay": audio_delay,
            "subtitle_delay": subtitle_delay, "subtitle_style": subtitle_style,
            "pretty_title": lambda _path: "New Film", "DEFAULTS": {"audio_gain": 0.0},
        },
    )
    w._closing = False
    w.cfg.update(direct=False, audio="original", quality="high")
    w.tracker = mock.Mock()
    w.tracker.value.return_value = None
    w.media = None
    stopped = {"value": False}
    previous.stop = mock.Mock(side_effect=lambda *_a, **_k: stopped.update(value=True))
    previous.mode = "transcode"
    previous.active = lambda: not stopped["value"]
    monkeypatch.setattr(streamer, "ffprobe", lambda _path: SimpleNamespace(direct_ok=False))
    monkeypatch.setattr(streamer, "require_compatible_ffmpeg", lambda: None)
    stop_calls = []

    class NewSession:
        mode = "transcode"
        state = None

        def start_transcode(self, *_args, **_kwargs):
            w.stop_stream()

        def stop(self, _device, *, send_stop=True):
            stop_calls.append(send_stop)

    monkeypatch.setattr(streamer, "Session", NewSession)
    w._cast_path(pathlib.Path("/new-film.mp4"), 0.0)

    assert stop_calls == [True, False]
    assert w._cast_failed.call_args.args == ("Cast cancelled during receiver handoff",)


def test_missing_receiver_rejects_without_touching_current_playback():
    w, previous = window(device="")
    reason = w._cast_path(pathlib.Path("/another.mkv"), 0.0)
    assert reason == "Choose a room receiver before casting"
    assert w.session is previous
    assert not w.busy
    w._unload_local_video.assert_not_called()
    w.local_playback.stop.assert_not_called()
    w._cast_failed.assert_not_called()
