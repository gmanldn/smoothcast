"""Playback-quality benchmark (SC-048 #57).

Measures how fast this machine encodes a short synthetic 1080p clip and turns
that into an explicit 720p/1080p/4K recommendation with trade-offs. The
measurement is a bounded local FFmpeg run on a generated test pattern; it never
touches the user's media, a receiver or the system audio.
"""
from __future__ import annotations

import re
import subprocess

_FPS = re.compile(r"fps=\s*([\d.]+)")


def parse_fps(text: str | None) -> float | None:
    """Return the last positive ``fps=`` value from FFmpeg progress output."""
    matches = _FPS.findall(text or "")
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except ValueError:
        return None
    return value if value > 0 else None


def recommend(encode_fps: float | None, source_fps: float) -> dict:
    """Recommend an output tier from measured encode speed vs source frame rate.

    ``ratio = encode_fps / source_fps``; a ratio at or above 1.0 keeps real time.
    """
    if not encode_fps or encode_fps <= 0 or not source_fps or source_fps <= 0:
        return {
            "tier": "720p", "realtime": False, "headroom": 0.0,
            "reason": "No reliable encode measurement; start conservative.",
            "tradeoff": "Lower CPU and bandwidth, softer detail.",
        }
    ratio = encode_fps / source_fps
    headroom = max(0.0, (ratio - 1.0) * 100.0)
    if ratio >= 2.0:
        return {
            "tier": "4K", "realtime": True, "headroom": headroom,
            "reason": f"Encoder runs {ratio:.2f}x the source frame rate.",
            "tradeoff": "Highest CPU and bandwidth; needs a strong machine and network.",
        }
    if ratio >= 1.0:
        return {
            "tier": "1080p", "realtime": True, "headroom": headroom,
            "reason": f"Encoder keeps up at {ratio:.2f}x real time.",
            "tradeoff": "Balanced CPU, bandwidth and detail.",
        }
    if ratio >= 0.6:
        return {
            "tier": "720p", "realtime": False, "headroom": 0.0,
            "reason": f"Encoder is slower than real time ({ratio:.2f}x).",
            "tradeoff": "Lighter CPU and bandwidth; expect buffering at 1080p.",
        }
    return {
        "tier": "720p", "realtime": False, "headroom": 0.0,
        "reason": f"Encoder is well below real time ({ratio:.2f}x).",
        "tradeoff": "Use 720p and a lower frame rate; buffering is likely otherwise.",
    }


def probe_command(seconds: int = 4, height: int = 1080, encoder: str = "libx264") -> list[str]:
    width = max(2, round(height * 16 / 9 / 2) * 2)
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=30",
        "-t", str(seconds), "-c:v", encoder, "-preset", "veryfast",
        "-f", "null", "-",
    ]


def run_probe(seconds: int = 4, height: int = 1080, encoder: str = "libx264",
              *, runner=None) -> float | None:
    """Run a bounded synthetic encode and return the measured frames/second."""
    run = subprocess.run if runner is None else runner
    try:
        result = run(
            probe_command(seconds, height, encoder),
            capture_output=True, text=True, timeout=max(20, seconds * 15),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return parse_fps(getattr(result, "stderr", None))
