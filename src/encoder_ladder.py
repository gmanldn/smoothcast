"""Pure FFmpeg capability parsing and encoder ladder selection (#217). No I/O.

Parses ``ffmpeg -encoders`` / ``-filters`` text, reports missing required
filters, and orders candidate H.264 encoders for a platform. A dry-run result
supplied by the caller decides which candidates are *verified*; libx264 is the
guaranteed final rung.
"""
from __future__ import annotations

import re

REQUIRED_FILTERS = ("subtitles", "overlay", "acompressor", "alimiter", "loudnorm")
FILTER_HINTS = {
    "subtitles": "FFmpeg was built without libass, so burned-in subtitles are unavailable.",
    "overlay": "FFmpeg is missing the overlay filter.",
    "acompressor": "FFmpeg is missing the acompressor filter (dynamic range control).",
    "alimiter": "FFmpeg is missing the alimiter filter.",
    "loudnorm": "FFmpeg is missing the loudnorm filter (loudness normalisation).",
}
LADDER = {
    "darwin": ("h264_videotoolbox",),
    "win32": ("h264_nvenc", "h264_qsv", "h264_amf"),
    "linux": ("h264_nvenc", "h264_qsv", "h264_vaapi"),
}
FALLBACK = "libx264"

_ENC = re.compile(r"^\s*V[\w.]{5}\s+(\S+)", re.M)
_FILT = re.compile(r"^\s*[T.][S.][C.]?\s+(\S+)\s", re.M)


def parse_encoders(text: str) -> frozenset[str]:
    """Names of video encoders from ``ffmpeg -encoders`` output."""
    return frozenset(m for m in _ENC.findall(text or "") if m != "=")


def parse_filters(text: str) -> frozenset[str]:
    """Filter names from ``ffmpeg -filters`` output."""
    return frozenset(m for m in _FILT.findall(text or "") if m != "=")


def missing_filters(filters: frozenset[str]) -> list[str]:
    """Plain-language problems for every required filter that is absent."""
    return [FILTER_HINTS[f] for f in REQUIRED_FILTERS if f not in filters]


def ladder(platform: str, encoders: frozenset[str], verified: dict | None = None) -> list[str]:
    """Encoders to try in order: verified hardware, always ending with libx264.

    ``verified`` maps encoder -> bool from a dry-run; entries not yet tested are
    omitted from the result (never trusted on name alone). A False result removes
    the candidate.
    """
    verified = verified or {}
    chosen = [e for e in LADDER.get(platform, LADDER["linux"])
              if e in encoders and verified.get(e) is True]
    return chosen + [FALLBACK]


def untested(platform: str, encoders: frozenset[str], verified: dict | None = None) -> list[str]:
    """Hardware candidates present in the build that still need a dry-run."""
    verified = verified or {}
    return [e for e in LADDER.get(platform, LADDER["linux"]) if e in encoders and e not in verified]


def cache_key(ffmpeg_version: str, gpu: str = "", driver: str = "") -> str:
    """Invalidate verification when FFmpeg, GPU or driver changes."""
    return "|".join(re.sub(r"\s+", " ", str(p or "")).strip() for p in (ffmpeg_version, gpu, driver))
