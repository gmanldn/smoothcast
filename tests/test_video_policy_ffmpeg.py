"""Real-FFmpeg checks for the automatic crop/deinterlace policies (issue #54).

Tiny synthetic clips prove the parsers and filters work against the actual
``cropdetect``/``idet`` output and a real encode. They run only where an FFmpeg
with libx264 is guaranteed: the CI "FFmpeg MKV/SRT runtime integration" job sets
SMOOTHCAST_REAL_FFMPEG=1. Locally: ``SMOOTHCAST_REAL_FFMPEG=1 pytest tests/test_video_policy_ffmpeg.py``.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import streamer
import video_policy as vp
from video_policy import Crop, Plan

LETTERBOX = Crop(640, 360, 0, 60)

needs_ffmpeg = pytest.mark.skipif(
    os.environ.get("SMOOTHCAST_REAL_FFMPEG") != "1" or not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="set SMOOTHCAST_REAL_FFMPEG=1 with ffmpeg and ffprobe installed")


def make_clip(tmp_path, name, source, extra_vf="", flags=()):
    path = tmp_path / name
    vf = ["-vf", extra_vf] if extra_vf else []
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source, *vf,
               "-pix_fmt", "yuv420p", "-c:v", "libx264", *flags, "-y", str(path)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        pytest.fail(f"the integration job guarantees libx264 but encoding failed: {exc}")
    return path


@needs_ffmpeg
def test_real_cropdetect_finds_letterbox_bars(tmp_path):
    clip = make_clip(tmp_path, "letter.mp4",
                     "testsrc2=size=640x480:rate=25:duration=6,"
                     "drawbox=x=0:y=0:w=640:h=60:color=black:t=fill,"
                     "drawbox=x=0:y=420:w=640:h=60:color=black:t=fill")
    assert vp.detect_crop(str(clip), 6.0, 640, 480) == LETTERBOX


@needs_ffmpeg
def test_real_idet_separates_interlaced_from_progressive(tmp_path):
    top = make_clip(tmp_path, "tff.mp4", "testsrc2=size=640x480:rate=25:duration=6",
                    "interlace=scan=tff", ("-flags", "+ilme+ildct"))
    bottom = make_clip(tmp_path, "bff.mp4", "testsrc2=size=640x480:rate=25:duration=6",
                       "interlace=scan=bff", ("-flags", "+ilme+ildct"))
    still = make_clip(tmp_path, "prog.mp4", "smptebars=size=640x480:rate=25:duration=6")
    assert vp.detect_interlaced(str(top), 6.0) is True
    assert vp.detect_interlaced(str(bottom), 6.0) is True
    assert vp.detect_interlaced(str(still), 6.0) is False


@needs_ffmpeg
def test_real_encode_with_the_plan_chain_yields_the_cropped_size(tmp_path):
    clip = make_clip(tmp_path, "letter.mp4",
                     "testsrc2=size=640x480:rate=25:duration=3,"
                     "drawbox=x=0:y=0:w=640:h=60:color=black:t=fill,"
                     "drawbox=x=0:y=420:w=640:h=60:color=black:t=fill")
    out = tmp_path / "out.mp4"
    vf = streamer.Session()._filter_args(False, None, True, 1.0, video_size=(640, 480),
                                         video_plan=Plan(deinterlace=True, crop=LETTERBOX))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip), *vf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(out)],
                   check=True, capture_output=True, timeout=60)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(out)],
                           check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    assert probe == "640,360"
