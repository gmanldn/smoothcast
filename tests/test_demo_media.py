"""Demo media generator (#454 slice 1): exact commands, idempotent, real-FFmpeg spot check."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo_media", ROOT / "scripts/demo_media.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        Path(command[-1]).write_bytes(b"x")  # pretend ffmpeg wrote the output
        return subprocess.CompletedProcess(command, 0)


def test_commands_are_deterministic_and_bounded(tmp_path):
    run = FakeRun()
    files = demo.make_demo_media(tmp_path, run)
    assert [p.name for p in files] == ["demo-video.mp4", "demo-movie.mkv", "demo-movie.en.srt", "demo-music.mp3"]
    assert len(run.calls) == 3
    video = run.calls[0]
    assert video[0] == "ffmpeg" and "testsrc2=size=1280x720:rate=30:duration=8" in video
    assert "libx264" in video and "yuv420p" in video and "+faststart" in video
    assert "libmp3lame" in run.calls[2]
    assert (tmp_path / "demo-movie.en.srt").read_text().count("-->") == 3


def test_second_run_generates_nothing(tmp_path):
    run = FakeRun()
    demo.make_demo_media(tmp_path, run)
    run.calls.clear()
    demo.make_demo_media(tmp_path, run)
    assert run.calls == []


def test_empty_leftover_file_is_regenerated(tmp_path):
    (tmp_path / "demo-video.mp4").write_bytes(b"")
    run = FakeRun()
    demo.make_demo_media(tmp_path, run)
    assert any("demo-video.mp4" in c[-1] for c in run.calls)


def test_missing_ffmpeg_gives_a_civil_message(tmp_path, capsys):
    def missing(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    assert demo.main([str(tmp_path / "y")], missing) == 1
    err = capsys.readouterr().err
    assert "FFmpeg is installed" in err and "Traceback" not in err


def test_usage_error():
    assert demo.main([]) == 2


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")) or
                    os.environ.get("SMOOTHCAST_REAL_FFMPEG") != "1", reason="set SMOOTHCAST_REAL_FFMPEG=1")
def test_real_ffmpeg_output_has_expected_streams(tmp_path):
    files = demo.make_demo_media(tmp_path)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(files[0])],
        check=True, capture_output=True, text=True, timeout=30)
    data = json.loads(probe.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 1280, 720)
    assert any(s["codec_name"] == "aac" for s in data["streams"])
    assert abs(float(data["format"]["duration"]) - 8.0) < 0.5
