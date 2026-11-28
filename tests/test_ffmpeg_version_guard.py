"""#242: supported FFmpeg release guard is pure, fast and headless.

Every subprocess is injected/mocked. These tests NEVER execute FFmpeg, GTK,
a Chromecast command or the user's active media.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

import ffmpeg_compat
import streamer


@pytest.mark.parametrize("header,expected", [
    ("ffmpeg version 4.4 Copyright\n", (4, 4)),
    ("ffmpeg version n5.0 Copyright", (5, 0)),
    ("ffmpeg version 5.1.6-0+deb12u1 Copyright", (5, 1)),
    ("ffmpeg version 6.1.1-3ubuntu5 Copyright", (6, 1)),
    ("ffmpeg version 7.0-full_build-www.gyan.dev", (7, 0)),
    ("ffmpeg version 8.0-static", (8, 0)),
])
def test_normalises_upstream_distro_and_windows_banners(header, expected):
    assert ffmpeg_compat.parse_version(header) == expected


@pytest.mark.parametrize("header", [
    "", "ffmpeg version N-114500-g12345", "ffmpeg version unknown",
    "ffprobe version 6.1", "ffmpeg version 3", "ffmpeg version 5.x",
    "malicious ffmpeg version 500.0", "ffmpeg version 4.4\nffmpeg version 9.0",
])
def test_unrecognised_or_development_banners_cannot_bypass_floor(header):
    if header == "ffmpeg version 4.4\nffmpeg version 9.0":
        assert ffmpeg_compat.parse_version(header) == (4, 4)
    else:
        assert ffmpeg_compat.parse_version(header) is None


def run_ffmpeg(header="ffmpeg version 6.1.2", *, returncode=0):
    seen = []

    def fake(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, stdout=header, stderr="")
    return seen, fake


def test_supported_binary_version_passes_with_bounded_no_shell_probe():
    seen, run = run_ffmpeg("ffmpeg version 5.0.0 Copyright")
    assert ffmpeg_compat.require_supported_ffmpeg(run=run) == (5, 0)
    args, kwargs = seen[0]
    assert args == ["ffmpeg", "-version"]
    assert kwargs["timeout"] == ffmpeg_compat.VERSION_TIMEOUT
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL


@pytest.mark.parametrize("header", ["ffmpeg version 4.4.2", "ffmpeg version n4.3.1"])
def test_outdated_ffmpeg_reports_actual_version_and_required_features(header):
    _, run = run_ffmpeg(header)
    with pytest.raises(ffmpeg_compat.FFmpegVersionError, match=r"too old.*FFmpeg 5\.0"):
        ffmpeg_compat.require_supported_ffmpeg(run=run)


@pytest.mark.parametrize("problem,message", [
    (FileNotFoundError("no ffmpeg"), "unavailable"),
    (OSError("loader missing"), "unavailable"),
    (subprocess.TimeoutExpired(["ffmpeg", "-version"], 4), "timed out"),
])
def test_absent_broken_or_hung_binary_produces_actionable_error(problem, message):
    with pytest.raises(ffmpeg_compat.FFmpegVersionError, match=message):
        ffmpeg_compat.require_supported_ffmpeg(
            run=mock.Mock(side_effect=problem))


def test_failed_binary_and_unknown_banner_are_rejected():
    for banner,code in (("ffmpeg version 7.0", 1), ("snapshot-non-release", 0)):
        _, run = run_ffmpeg(banner, returncode=code)
        with pytest.raises(ffmpeg_compat.FFmpegVersionError, match="FFmpeg"):
            ffmpeg_compat.require_supported_ffmpeg(run=run)


def test_streamer_wraps_version_error_as_user_visible_stream_error():
    with mock.patch.object(
        streamer.ffmpeg_compat, "require_supported_ffmpeg",
        side_effect=ffmpeg_compat.FFmpegVersionError("Install FFmpeg 5.0 or newer")
    ):
        with pytest.raises(streamer.StreamError, match="Install FFmpeg 5.0"):
            streamer.require_compatible_ffmpeg()


def test_incompatible_encoder_aborts_before_route_cache_or_process():
    media = streamer.MediaInfo(path=Path("/no/film.mkv"), duration=100)
    with mock.patch.object(
        streamer, "require_compatible_ffmpeg",
        side_effect=streamer.StreamError("FFmpeg 4.4 is too old")
    ), mock.patch.object(streamer, "host_ip") as host, \
       mock.patch.object(streamer.subprocess, "Popen") as popen:
        with pytest.raises(streamer.StreamError, match="too old"):
            streamer.Session().start_transcode(
                media, 0, device="TV", quality="balanced",
                audio_profile="original", subs_file=None,
                burn_subs=False, title="Film",
            )
    host.assert_not_called()
    popen.assert_not_called()


def test_ui_checks_runtime_before_stopping_existing_cast_for_new_or_restart():
    from gui_source import main_window_methods
    actions = main_window_methods()
    cast = actions["_cast_path"].split("def work():", 1)[1]
    restart = actions["_restart_at"].split("def work():", 1)[1]
    # The check runs in the parallel preflight; its result is collected (and any
    # failure raised) before the previous cast is stopped.
    assert "workers.submit(streamer.require_compatible_ffmpeg)" in cast
    assert cast.index("ffmpeg_future.result()") < cast.index("previous.stop(device")
    assert restart.index("streamer.require_compatible_ffmpeg()") < (
        restart.index("session.stop(device, send_stop=False)")
    )


def test_compatibility_guard_is_packaged_and_release_floor_documented():
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "pyproject.toml").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert '"ffmpeg_compat"' in manifest
    assert "FFmpeg 5.0 or newer" in readme


def test_good_version_is_remembered_per_binary(monkeypatch, tmp_path):
    binary = tmp_path / "ffmpeg"
    binary.write_text("x")
    monkeypatch.setattr(ffmpeg_compat.media_tools, "resolve_media_tool", lambda n: str(binary))
    ffmpeg_compat._verified.clear()
    calls = []

    def fake(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ffmpeg version 7.1.5", stderr="")
    monkeypatch.setattr(ffmpeg_compat.subprocess, "run", fake)
    assert ffmpeg_compat.require_supported_ffmpeg() == (7, 1)
    assert ffmpeg_compat.require_supported_ffmpeg() == (7, 1)
    assert len(calls) == 1
