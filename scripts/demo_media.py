#!/usr/bin/env python3
"""Generate small, reproducible demo clips with FFmpeg (issue #454, slice 1).

Nothing is downloaded or committed: the clips are synthetic (test pattern and
tones). The generator is idempotent, runs no GUI and talks to no receiver.

    python3 scripts/demo_media.py DIRECTORY
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Callable

SRT = """1
00:00:00,500 --> 00:00:02,500
SmoothCast demo: subtitles work.

2
00:00:03,000 --> 00:00:05,000
Pause, seek and cast from any device.

3
00:00:05,500 --> 00:00:07,500
This clip is generated, not downloaded.
"""

_VIDEO = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
          "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8"]
_H264 = ["-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
         "-preset", "veryfast", "-crf", "30", "-g", "60", "-c:a", "aac", "-b:a", "96k", "-shortest"]


def _commands(directory: Path) -> list[tuple[Path, list[str]]]:
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    return [
        (directory / "demo-video.mp4", [*base, *_VIDEO, *_H264, "-movflags", "+faststart",
                                        str(directory / "demo-video.mp4")]),
        (directory / "demo-movie.mkv", [*base, *_VIDEO, *_H264, str(directory / "demo-movie.mkv")]),
        (directory / "demo-music.mp3", [*base, "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=6",
                                        "-c:a", "libmp3lame", "-b:a", "128k",
                                        "-metadata", "title=SmoothCast demo tone",
                                        "-metadata", "artist=SmoothCast",
                                        str(directory / "demo-music.mp3")]),
    ]


def make_demo_media(directory: Path | str, run: Callable[..., object] = subprocess.run) -> list[Path]:
    """Create any missing demo files and return all of them (video, movie, subtitles, music)."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for target, command in _commands(out):
        if not (target.exists() and target.stat().st_size > 0):
            run(command, check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        made.append(target)
    subtitles = out / "demo-movie.en.srt"
    if not (subtitles.exists() and subtitles.stat().st_size > 0):
        subtitles.write_text(SRT, encoding="utf-8")
    made.insert(2, subtitles)
    return made


def main(argv: list[str], run: Callable[..., object] = subprocess.run) -> int:
    if len(argv) != 1:
        print("usage: demo_media.py DIRECTORY", file=sys.stderr)
        return 2
    try:
        files = make_demo_media(argv[0], run)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Demo media could not be created: {exc.__class__.__name__}. Check that FFmpeg is installed.",
              file=sys.stderr)
        return 1
    for path in files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
