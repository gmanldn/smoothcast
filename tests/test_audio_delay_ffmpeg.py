"""Real-FFmpeg timing check for the audio delay filters (issue #113).

A tone starts at 0.5 s. Applying the exact filters SmoothCast builds must move the
measured onset by the requested delay. Runs only where FFmpeg is guaranteed
(SMOOTHCAST_REAL_FFMPEG=1, as in the CI FFmpeg integration job).
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import audio_delay

needs_ffmpeg = pytest.mark.skipif(
    os.environ.get("SMOOTHCAST_REAL_FFMPEG") != "1" or not shutil.which("ffmpeg"),
    reason="set SMOOTHCAST_REAL_FFMPEG=1 with ffmpeg installed")

RATE = 16000
TONE = "aevalsrc='if(between(t,0.5,1.5),0.5*sin(2*PI*440*t),0)':s=16000:d=2"


def onset_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
    samples = memoryview(frames).cast("h")
    for index, value in enumerate(samples):
        if abs(value) > 1500:
            return index / rate
    raise AssertionError("no tone found in the output")


def render(tmp_path: Path, delay_ms: int) -> float:
    out = tmp_path / f"out_{delay_ms}.wav"
    chain = ",".join(audio_delay.filters(delay_ms))
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", TONE]
    if chain:
        command += ["-af", chain]
    command += ["-ac", "1", "-c:a", "pcm_s16le", "-y", str(out)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        pytest.fail(f"FFmpeg could not apply {chain!r}: {exc}")
    return onset_seconds(out)


@needs_ffmpeg
@pytest.mark.parametrize("delay_ms", [0, 300, 1000, -300, -450])
def test_the_built_filters_shift_the_audio_by_the_requested_amount(tmp_path, delay_ms):
    base = 0.5
    measured = render(tmp_path, delay_ms)
    assert measured == pytest.approx(base + delay_ms / 1000, abs=0.02)
