"""Stop state reports remote acknowledgement, not local cleanup success."""
from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dlna
import reliability_metrics
import streamer
from gui_source import main_window_methods


def test_cast_session_stop_returns_receiver_result(tmp_path, monkeypatch):
    monkeypatch.setattr(streamer, "ROOT", tmp_path)
    monkeypatch.setattr(streamer, "clear_session", mock.Mock())
    monkeypatch.setattr(streamer, "_terminate", mock.Mock())
    monkeypatch.setattr(streamer.castctl, "stop", mock.Mock(return_value=(False, "offline")))
    session = streamer.Session()
    session.state = streamer.SessionState(
        file="film.mp4", mode="direct", offset=0, duration=60,
        device="TV", title="Film",
    )
    session._playlist_name = "unmanaged.m3u8"
    session._segment_pattern = "unused-*.ts"
    session._stop_sampler = mock.Mock()

    assert session.stop("TV") is False
    streamer.castctl.stop.assert_called_once_with("TV")


def test_local_session_cleanup_without_remote_stop_reports_false(tmp_path, monkeypatch):
    monkeypatch.setattr(streamer, "ROOT", tmp_path)
    monkeypatch.setattr(streamer, "clear_session", mock.Mock())
    monkeypatch.setattr(streamer, "_terminate", mock.Mock())
    stop = mock.Mock()
    monkeypatch.setattr(streamer.castctl, "stop", stop)
    session = streamer.Session()
    session._playlist_name = "unmanaged.m3u8"
    session._segment_pattern = "unused-*.ts"
    session._stop_sampler = mock.Mock()

    assert session.stop("TV", send_stop=False) is False
    stop.assert_not_called()


@pytest.mark.parametrize(("failure", "expected"), [(False, True), (True, False)])
def test_dlna_session_stop_reports_soap_result(monkeypatch, failure, expected):
    session = dlna.Session()
    renderer = object()
    session.renderer = renderer
    session._owns_renderer = True
    send = mock.Mock(side_effect=dlna.DlnaError("unreachable") if failure else None)
    monkeypatch.setattr(dlna, "stop", send)

    assert session.stop("TV") is expected
    send.assert_called_once_with(renderer)


def make_window(stop_result):
    source = textwrap.indent(textwrap.dedent(main_window_methods()["stop_stream"]), "    ")
    jobs = []
    namespace = {
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **_kwargs:
                jobs.append((work, done, failed)),
        ),
        "playback_state": SimpleNamespace(hls_session_matches=lambda *_args: True),
        "castctl": SimpleNamespace(info=mock.Mock(), stop=mock.Mock(return_value=(True, ""))),
        "dlna": SimpleNamespace(stop=mock.Mock()),
        "save_config": mock.Mock(),
        "reliability_metrics": reliability_metrics,
    }
    exec(compile("class Window:\n" + source, "<stop-stream>", "exec"), namespace)
    window = namespace["Window"]()
    window.tracker = SimpleNamespace(value=lambda: None, clear=mock.Mock())
    window.media = None
    window.cfg = {}
    window.busy = False
    window._dlna_cancel = None
    window._preview_path = None
    window.external = False
    window.device_state = "PLAYING"
    window.session = SimpleNamespace(
        mode="direct", state=SimpleNamespace(mode="direct"),
        stop=mock.Mock(return_value=stop_result),
    )
    window.now_playing = "film.mp4"
    window._finished_handled = False
    window._record_watch = mock.Mock()
    window._refresh_controls = mock.Mock()
    window._device = lambda: "TV"
    window._dlna_renderer = lambda _device=None: None
    window._stop_monitor = mock.Mock()
    window._set_levels_hint = mock.Mock()
    window.toast = mock.Mock()
    window._console = mock.Mock()
    window._rebuild_queue = mock.Mock()
    window._poll_device = mock.Mock()
    window.testing = namespace
    window.jobs = jobs
    return window


@pytest.mark.parametrize(
    ("stop_result", "expected_toast"),
    [(True, "Stopped"), (False, "Local stream stopped; receiver did not confirm Stop")],
)
def test_stop_ui_reports_actual_receiver_acknowledgement(stop_result, expected_toast):
    window = make_window(stop_result)
    window.stop_stream()
    work, done, _failed = window.jobs.pop()
    result = work()
    done(result)

    assert result is stop_result
    window.toast.assert_called_once_with(expected_toast)
