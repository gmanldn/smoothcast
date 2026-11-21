"""P0 #22: exact subtitle choice survives HLS restart or fails before Stop.

GTK-independent tests execute the production restart handler with injected
workers; no receiver, FFmpeg or application window is launched.
"""
from __future__ import annotations

from pathlib import Path
import textwrap
from types import SimpleNamespace
from unittest import mock

import pytest
from gui_source import main_window_methods

import castctl
import streamer
import subtitle_restart


def state(*, subs="", burn=False, embedded=-1):
    return streamer.SessionState(
        file="/movie.mkv", mode="transcode", offset=33.0, duration=140.0,
        device="TV", title="Movie", subs=str(subs), burn_subs=burn,
        embedded_subtitle_index=embedded,
    )


def media(*tracks):
    return streamer.MediaInfo(
        path=Path("/movie.mkv"), duration=140.0, subtitle_tracks=list(tracks),
    )


def track(index=3, codec="subrip"):
    return streamer.SubtitleTrack(
        index=index, codec=codec, language="eng", default=True,
    )


def test_no_caption_keeps_no_caption_and_does_not_invent_forced_track():
    result = subtitle_restart.validate_restart(state(), media(track()))
    assert result == subtitle_restart.RestartSubtitles(None, False, None)
    assert subtitle_restart.validate_restart(None, media()).external is None


def test_original_external_srt_keeps_selected_file_and_burn_mode(tmp_path):
    path = tmp_path / "chosen.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    result = subtitle_restart.validate_restart(
        state(subs=path, burn=False), media(track())
    )
    assert result.external == path
    assert result.burn is False
    assert result.embedded_index is None
    burned = subtitle_restart.validate_restart(
        state(subs=path, burn=True), media(track())
    )
    assert burned.external == path
    assert burned.burn is True


def test_selected_filename_with_legal_trailing_space_is_not_normalised(tmp_path):
    filename = tmp_path / "captions.srt "
    filename.write_text("caption")
    # An unusual but valid filename must be preserved byte-for-byte.
    with pytest.raises(streamer.StreamError, match="missing or unsupported"):
        subtitle_restart.validate_restart(state(subs=filename), media())
    # The supported extension guard must not silently choose an unrelated
    # captions.srt file by trimming/normalising a selected filename.


def test_ass_subtitles_never_silently_disappear_if_old_burn_flag_is_false(tmp_path):
    path = tmp_path / "chosen.ass"
    path.write_text("[Script Info]\nTitle: chosen")
    result = subtitle_restart.validate_restart(
        state(subs=path, burn=False), media()
    )
    assert result.external == path
    assert result.burn is True


@pytest.mark.parametrize("suffix", [".srt", ".ass", ".vtt"])
def test_missing_chosen_sidecar_fails_instead_of_falling_back_to_none(tmp_path, suffix):
    missing = tmp_path / ("missing" + suffix)
    with pytest.raises(streamer.StreamError, match="missing or unsupported"):
        subtitle_restart.validate_restart(
            state(subs=missing), media(track())
        )


def test_rejects_bad_extension_without_reading_user_media(tmp_path):
    path = tmp_path / "selection.exe"
    path.write_bytes(b"example")
    with pytest.raises(streamer.StreamError, match="missing or unsupported"):
        subtitle_restart.validate_restart(state(subs=path), media())


def test_explicit_embedded_track_is_preserved_even_if_not_preferred(tmp_path):
    different_default = streamer.SubtitleTrack(index=2, codec="subrip", default=True)
    selected = streamer.SubtitleTrack(index=7, codec="ass", default=False, forced=True)
    result = subtitle_restart.validate_restart(
        state(embedded=7), media(different_default, selected)
    )
    assert result.embedded_index == 7
    assert result.burn is True
    assert result.external is None
    # FFprobe's forced disposition stays on the selected stream after reprobe.
    assert "forced" in selected.label


@pytest.mark.parametrize("available", [
    [],
    [track(index=1)],
    [track(index=7, codec="unsupported_image_format")],
])
def test_missing_or_unsupported_embedded_selection_never_changes_track(available):
    with pytest.raises(streamer.StreamError, match="no longer available"):
        subtitle_restart.validate_restart(state(embedded=7), media(*available))


def test_selected_bitmap_embedded_track_survives_restart():
    selected = track(index=7, codec="hdmv_pgs_subtitle")
    result = subtitle_restart.validate_restart(state(embedded=7), media(selected))
    assert result.embedded_index == 7
    assert result.burn is True


def test_conflicting_or_corrupt_selection_is_rejected(tmp_path):
    path = tmp_path / "chosen.srt"
    path.touch()
    with pytest.raises(streamer.StreamError, match="Conflicting"):
        subtitle_restart.validate_restart(
            state(subs=path, embedded=7), media(track(index=7))
        )
    s = state()
    s.embedded_subtitle_index = "7"
    with pytest.raises(streamer.StreamError, match="invalid"):
        subtitle_restart.validate_restart(s, media())


def restart_window(session):
    jobs = []
    method = main_window_methods()["_restart_at"]
    code = "class Extracted:\n" + textwrap.indent(textwrap.dedent(method), "    ")
    namespace = {
        "pathlib": __import__("pathlib"),
        "streamer": streamer,
        "audio_delay": __import__("audio_delay"),
        "subtitle_delay": __import__("subtitle_delay"),
        "subtitle_style": __import__("subtitle_style"),
        "subtitle_restart": subtitle_restart,
        "castctl": castctl,
        "DEFAULTS": {"audio_gain": 0.0},
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None, **_kwargs:
                                 jobs.append((work, done, failed))),
    }
    exec(compile(code, "<subtitle-restart-worker>", "exec"), namespace)

    class Window(namespace["Extracted"]):
        def __init__(self):
            self.cfg = {
                "quality": "balanced", "audio": "original",
                "playback_speed": 1.0, "rotation": 0, "audio_gain": 0.0,
            }
            self.session = session
            self.media = None
            self.device_state = "PLAYING"
            self.tracker = SimpleNamespace(known=False, playing=True)
            for method_name in (
                "_cast_failed", "_update_audio_choices", "_start_monitor",
                "_set_levels_hint", "_refresh_controls", "_poll_device",
                "_console", "_stop_monitor", "toast",
            ):
                setattr(self, method_name, mock.Mock())

        def _device(self):
            return "TV"

        def _device_host(self, device):
            return "192.168.1.20"

    window = Window()
    window._restart_at(session, 54.0)
    assert len(jobs) == 1
    return window, jobs[0]


@pytest.mark.parametrize("kind", ["missing_external", "missing_embedded"])
def test_invalid_saved_choice_keeps_original_cast_running(kind, tmp_path):
    path = tmp_path / "not-present.srt"
    selected = (
        state(subs=path) if kind == "missing_external"
        else state(embedded=7)
    )
    session = mock.Mock(mode="transcode", state=selected)
    window, (work, _, failed) = restart_window(session)
    source_media = media(track(index=1))
    with mock.patch.object(streamer, "ffprobe", return_value=source_media):
        with pytest.raises(streamer.StreamError) as problem:
            work()
    session.stop.assert_not_called()
    session.start_transcode.assert_not_called()
    assert window.session is session
    assert window.tracker.playing is True
    window.busy = True
    failed(str(problem.value))
    assert window.busy is False
    window._cast_failed.assert_not_called()
    window._stop_monitor.assert_not_called()
    window._set_levels_hint.assert_not_called()
    window._console.assert_called_once()
    window._refresh_controls.assert_called_once()


def test_dead_original_cast_uses_normal_cleanup_path(tmp_path):
    s = state(subs=tmp_path / "missing.srt")
    session = mock.Mock(mode="transcode", state=s)
    session.active.return_value = False
    window, (work, _, failed) = restart_window(session)
    with mock.patch.object(streamer, "ffprobe", return_value=media()):
        with pytest.raises(streamer.StreamError):
            work()
    failed("Selected subtitle file is missing")
    window._cast_failed.assert_called_once()
    window._console.assert_not_called()


def test_restarted_cast_gets_exact_saved_sidecar_and_embedded_index(tmp_path):
    external = tmp_path / "chosen.srt"
    external.write_text("caption")
    for selection, expected_external, expected_index in (
        (state(subs=external, burn=True), external, None),
        (state(embedded=7), None, 7),
    ):
        session = mock.Mock(mode="transcode", state=selection)
        window, (work, _, _) = restart_window(session)
        source_media = media(track(index=7))
        with mock.patch.object(streamer, "ffprobe", return_value=source_media), \
             mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)):
            work()
        session.stop.assert_called_once_with("TV", send_stop=False)
        args = session.start_transcode.call_args
        assert args.args[1] == 54.0
        assert args.kwargs["subs_file"] == expected_external
        assert args.kwargs["embedded_subtitle_index"] == expected_index
        assert args.kwargs["burn_subs"] is True
        assert window.session is session


def test_handler_validation_precedes_destructive_stop_and_keeps_gui_under_budget():
    """INV-004: Subtitle validation must precede existing cast cleanup."""
    """INV-004: Validate subtitle choice before stopping an existing cast."""
    text = main_window_methods()["_restart_at"]
    assert text.index("subtitle_restart.validate_restart(state, media, delay)") < (
        text.index("session.stop(device, send_stop=False)")
    )
    assert "subs_file=captions.external" in text
    assert "embedded_subtitle_index=captions.embedded_index" in text
    source = Path(__file__).resolve().parents[1] / "src/cast_session.py"
    assert len(source.read_bytes().replace(b"\r\n", b"\n")) < 48000
