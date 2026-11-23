"""Aspect overrides are bounded and reproducible without a receiver."""
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import aspect_override
import config_control
import dlna
import streamer
from test_config_control import real_defaults


def test_original_and_invalid_overrides_leave_the_filter_chain_unchanged():
    assert aspect_override.normalize("corrupt") == "original"
    assert aspect_override.filters("original") == []
    assert aspect_override.filters("invalid;stop") == []
    assert streamer.Session()._filter_args(False, None, True, 1.0) == []


def test_config_accepts_only_known_aspect_override_values():
    defaults = real_defaults()
    assert config_control.sanitise_config({"aspect_override": "fill"}, defaults)["aspect_override"] == "fill"
    assert config_control.sanitise_config({"aspect_override": "invalid"}, defaults)["aspect_override"] == "original"


def test_cast_filter_applies_geometry_after_rotation_and_before_gpu_upload():
    _, graph = streamer.Session()._filter_args(
        False, None, False, 1.0, 90, aspect_mode="4:3", video_size=(3840, 2160),
    )
    assert graph == "hwdownload,format=nv12,transpose=1,scale=1440:1080,setsar=1,hwupload"


def test_dlna_override_encodes_a_video_that_would_otherwise_remux(tmp_path, monkeypatch):
    source = tmp_path / "film.mkv"
    source.write_bytes(b"video")
    target = tmp_path / "prepared.mp4"
    media = streamer.MediaInfo(
        path=source, vcodec="h264", pix_fmt="yuv420p", width=640, height=480, fps=25,
    )

    def encode(args, **_options):
        Path(args[-1]).write_bytes(b"prepared video")
        process = mock.Mock()
        process.poll.return_value = 0
        process.returncode = 0
        return process

    conversion = mock.Mock(side_effect=encode)
    monkeypatch.setattr(dlna.subprocess, "Popen", conversion)
    dlna.prepare_mp4(media, target, aspect_mode="4:3")
    args = conversion.call_args.args[0]
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-vf") + 1] == "scale=1440:1080,setsar=1"
    assert source.read_bytes() == b"video"


@pytest.mark.parametrize(("mode", "size"), [
    ("16:9", "640x360"), ("4:3", "480x360"), ("fit", "640x360"),
    ("fill", "640x360"), ("crop", "426x240"),
])
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires FFmpeg")
def test_preview_geometry_handles_anamorphic_source(mode, size):
    filters = aspect_override.filters(mode, width=640, height=360)
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-filter_threads", "1",
        "-f", "lavfi", "-i", "color=size=320x240,setsar=2",
        "-vf", ",".join([*filters, "showinfo"]), "-frames:v", "1", "-f", "null", "-",
    ], capture_output=True, text=True, timeout=10, check=True)
    assert f"sar:1/1 s:{size}" in result.stderr
