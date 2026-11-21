"""P0 #18: direct receiver acceptance and HLS fallback, GTK-free."""
from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

import pytest
from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import audio_delay
import direct_probe
import playback_state
import streamer
import subtitle_delay
import subtitle_style


def test_direct_status_classifier_is_conservative():
    assert direct_probe.classify(
        {"player_state": "PLAYING", "title": "Film"}, "film",
    ) == "accepted"
    assert direct_probe.classify(
        {"player_state": "PAUSED", "title": "Film"}, "Film",
    ) == "accepted"
    assert direct_probe.classify(
        {"player_state": "PLAYING", "title": "Other"}, "Film",
    ) == "foreign"
    assert direct_probe.classify(
        {"player_state": "PLAYING", "title": ""}, "Film",
    ) == "uncertain"
    assert direct_probe.classify(None, "Film") == "uncertain"
    assert direct_probe.classify(
        {"player_state": "BUFFERING", "title": "Film"}, "Film",
    ) == "uncertain"
    assert direct_probe.classify(
        {"player_state": "IDLE", "title": ""}, "Film",
    ) == "idle"


@pytest.mark.parametrize(
    "states, expected",
    [
        (["IDLE", "IDLE", "IDLE"], "rejected"),
        (["IDLE", "PLAYING"], "accepted"),
        ([None, "IDLE", "IDLE"], "uncertain"),
        (["IDLE", "BUFFERING", "IDLE"], "uncertain"),
        ([None, None, None], "uncertain"),
    ],
)
def test_bounded_direct_probe_only_falls_back_after_consecutive_idle(states, expected):
    observed = iter(states)
    calls = []
    sleep = []
    def get_info(device):
        calls.append(device)
        state = next(observed)
        if state is None:
            return None
        return {"player_state": state, "title": "Film" if state == "PLAYING" else ""}

    result = direct_probe.verify_direct_start(
        "TV A", "Film", get_info=get_info, pause=sleep.append,
    )
    assert result == expected
    assert 1 <= len(calls) <= 3
    assert all(device == "TV A" for device in calls)
    assert len(sleep) == len(calls) - 1
    assert all(seconds == 0.6 for seconds in sleep)


def test_direct_probe_never_replaces_known_foreign_video():
    calls = []
    with pytest.raises(direct_probe.ForeignPlayback, match="different media"):
        direct_probe.verify_direct_start(
            "TV A", "Film",
            get_info=lambda device: {"player_state": "PLAYING", "title": "Other"},
            pause=calls.append,
        )
    assert not calls


def test_network_errors_leave_direct_cast_uncertain_instead_of_overwriting():
    def offline(device):
        raise OSError("timeout")

    assert direct_probe.verify_direct_start(
        "TV A", "Film", get_info=offline, pause=lambda _: None,
    ) == "uncertain"
    for kwargs in ({"attempts": 0}, {"attempts": 20}, {"interval": 10}):
        with pytest.raises(ValueError):
            direct_probe.verify_direct_start(
                "TV A", "Film", get_info=offline, pause=lambda _: None, **kwargs
            )


def cast_worker(status="rejected"):
    source = main_window_methods()["_cast_path"]
    code = "class Handlers:\n" + textwrap.indent(textwrap.dedent(source), "    ")
    jobs = []
    first, second = mock.Mock(), mock.Mock()
    first.state = None
    second.state = None
    fake_streamer = SimpleNamespace(
        StreamError=streamer.StreamError,
        Session=mock.Mock(side_effect=[first, second]),
        CAST_SUBTITLE_EXTS=streamer.CAST_SUBTITLE_EXTS,
        require_compatible_ffmpeg=mock.Mock(return_value=(7, 0)),
        normalize_rotation=streamer.normalize_rotation,
        ffprobe=mock.Mock(
            return_value=SimpleNamespace(path=Path("/film.mp4"), direct_ok=True)
        ),
    )
    probe = mock.Mock(return_value=status)
    namespace = {
        "playback_state": playback_state,
        "audio_delay": audio_delay,
        "subtitle_delay": subtitle_delay,
        "subtitle_style": subtitle_style,
        "streamer": fake_streamer,
        "direct_probe": SimpleNamespace(
            verify_direct_start=probe,
            ForeignPlayback=direct_probe.ForeignPlayback,
        ),
        "dlna": SimpleNamespace(),
        "threading": SimpleNamespace(Event=lambda: None),
        "pathlib": __import__("pathlib"),
        "pretty_title": lambda path: path.stem,
        "DEFAULTS": {"audio_gain": 0.0},
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **_kwargs: jobs.append((work, done, failed))
        ),
    }
    exec(compile(code, "<direct-handoff>", "exec"), namespace)

    class Window(namespace["Handlers"]):
        def __init__(self):
            self.cfg = {
                "positions": {}, "subs": "pick", "burn_subs": False,
                "quality": "balanced", "audio": "original", "audio_gain": 0.0,
                "direct": True, "playback_speed": 1.0, "rotation": 0,
                "audio_track_by_file": {}, "subtitle_track_by_file": {},
            }
            self.busy = False
            self.session = None
            self._closing = False
            self.external = False
            self.now_playing = None
            self._preview_path = None
            self._local_video_path = None
            self._preview_generation = 0
            self._preview_pending = None
            self._preview_position = 0.0
            self._preflight_ok = set()
            self._finished_handled = False
            self.local_playback = SimpleNamespace(stop=lambda: None)
            self._unload_local_video = lambda: None
            self._refresh_controls = lambda: None
            self._device = lambda: "TV A"
            self._dlna_renderer = lambda device: None
            self._device_host = lambda device: "192.168.1.10"
            self._resolve_subs = lambda path: Path("/captions.srt")
            self.toast = mock.Mock()
    w = Window()
    w._cast_path(Path("/film.mp4"), 41.25)
    assert len(jobs) == 1
    return jobs[0][0], first, second, probe, fake_streamer


def test_repeated_idle_falls_back_to_hls_preserving_position_and_srt():
    work, first, second, probe, fake = cast_worker(status="rejected")
    second.start_transcode.return_value = None
    selected, media = work()
    assert selected is second
    first.start_direct.assert_called_once()
    first_kwargs = first.start_direct.call_args.kwargs
    assert first_kwargs["offset"] == 41.25
    assert first_kwargs["subs_file"] == Path("/captions.srt")
    first.stop.assert_called_once_with("TV A", send_stop=False)
    second.start_transcode.assert_called_once()
    new_args = second.start_transcode.call_args
    assert new_args.args[1] == 41.25
    assert new_args.kwargs["subs_file"] == Path("/captions.srt")
    assert new_args.kwargs["audio_track_index"] == -1
    assert new_args.kwargs["device"] == "TV A"
    probe.assert_called_once_with("TV A", "film")


def test_receiver_acceptance_or_unknown_status_keeps_direct_cast():
    for status in ("accepted", "uncertain"):
        work, first, second, _, fake = cast_worker(status=status)
        selected, _ = work()
        assert selected is first
        first.stop.assert_not_called()
        second.start_transcode.assert_not_called()
        assert fake.Session.call_count == 1


def test_foreign_active_stream_blocks_auto_hls_and_never_sends_stop():
    work, first, second, probe, fake = cast_worker(status="unimportant")
    probe.side_effect = direct_probe.ForeignPlayback("foreign stream")
    with pytest.raises(direct_probe.ForeignPlayback):
        work()
    first.stop.assert_called_once_with("TV A", send_stop=False)
    second.start_transcode.assert_not_called()
    assert fake.Session.call_count == 1


def test_handoff_probe_is_after_direct_command_and_before_success():
    source = main_window_methods()["_cast_path"]
    start = source.index("session.start_direct(")
    verify = source.index("direct_probe.verify_direct_start(")
    done = source.index("return session, media", verify)
    assert start < verify < done
