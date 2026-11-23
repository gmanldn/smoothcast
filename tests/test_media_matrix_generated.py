"""FFmpeg-generated playback corpus spot checks (#513), headless and offline.

These tiny clips prove FFmpeg -> real FFprobe metadata flow, not that Cast/DLNA
receivers accept any source. Each codec/container combination is a local fixture.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import streamer  # noqa: E402

# Six distinct container/codec combinations; no downloaded videos.
CASES = (
    ("mp4", "mpeg4", "mpeg4"),
    ("mkv", "mpeg4", "mpeg4"),
    ("avi", "mpeg4", "mpeg4"),
    ("mov", "mpeg4", "mpeg4"),
    ("ts", "mpeg2video", "mpeg2video"),
    ("webm", "libvpx", "vp8"),
)


@pytest.mark.parametrize(("extension", "encoder", "codec"), CASES)
def test_real_synthetic_video_is_parsed_by_production_ffprobe(
    tmp_path: Path, extension: str, encoder: str, codec: str,
) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are optional on developer workstations")
    path = tmp_path / f"generated.{extension}"
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10",
         "-frames:v", "5", "-an", "-c:v", encoder,
         "-pix_fmt", "yuv420p", "-threads", "1", str(path)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        # Encoder provisioning varies by platform. Do not suppress real
        # pipeline failures if the intended encoder IS installed.
        encoders = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        if result.returncode and not any(
            len(parts) > 1 and parts[1] == encoder
            for row in encoders.stdout.splitlines()
            if (parts := row.split()) and parts[0].startswith("V")
        ):
            pytest.skip(f"Optional encoder {encoder} is not available")
        pytest.fail(f"FFmpeg {encoder}/{extension} fixture failed: {result.stderr[-500:]}")
    assert path.is_file() and 0 < path.stat().st_size < 1_000_000
    media = streamer.ffprobe(path)
    assert media.vcodec == codec
    assert media.width == 160 and media.height == 90
    assert 0 < media.duration < 2
    assert media.path == path
    assert isinstance(media.direct_ok, bool)
    assert media.direct_reason
