"""Conservative Google Cast capability profiles by reported model (#11).

Pure and GTK-free. A model string is only a *hint*: it selects a documented
capability class, never a promise. Unknown or ambiguous models use the conservative
``CAST_BASELINE`` (H.264/AAC in MP4, 1080p, no HDR). Even an exact model
match is not a substitute for verified receiver capabilities. Learned per-receiver history
(``receiver_memory``) can still veto direct play on top of this.
"""
from __future__ import annotations

from capability_plan import CAST_BASELINE, ReceiverCaps

_MAX_MODEL_LENGTH = 128

# HEVC/VP9 4K HDR10 class: Chromecast Ultra and Google TV based streamers.
_UHD = ReceiverCaps.build(
    containers=("mp4", "webm"), video_codecs=("h264", "hevc", "vp9"),
    audio_codecs=("aac", "mp3", "opus", "vorbis", "flac"),
    subtitle_formats=("vtt",), max_height=2160, hdr=True, seekable=True)
# Speaker-only devices: no video of any kind.
_AUDIO_ONLY = ReceiverCaps.build(
    containers=("mp4", "mp3", "webm"), video_codecs=(),
    audio_codecs=("aac", "mp3", "opus", "vorbis", "flac"),
    subtitle_formats=(), max_height=None, hdr=False, seekable=True)

# Exact reported model names only; no substring matches or inferred variants.
_PROFILES: tuple[tuple[str, str, ReceiverCaps], ...] = (
    ("chromecast ultra", "Chromecast Ultra", _UHD),
    ("chromecast with google tv", "Chromecast with Google TV", CAST_BASELINE),
    ("chromecast with google tv (hd)", "Chromecast with Google TV (HD)", CAST_BASELINE),
    ("google tv streamer", "Google TV Streamer", _UHD),
    ("nest audio", "Nest Audio", _AUDIO_ONLY),
    ("google nest audio", "Nest Audio", _AUDIO_ONLY),
    ("nest mini", "Nest Mini", _AUDIO_ONLY),
    ("google nest mini", "Nest Mini", _AUDIO_ONLY),
    ("home mini", "Google Home Mini", _AUDIO_ONLY),
    ("google home mini", "Google Home Mini", _AUDIO_ONLY),
    ("google home", "Google Home", _AUDIO_ONLY),
)


def _norm(value: object) -> str:
    if (not isinstance(value, str) or len(value) > _MAX_MODEL_LENGTH
            or not value.isascii() or not value.isprintable()):
        return ""
    return " ".join(value.lower().split())


def profile_for_cast_model(model: object, manufacturer: object = "") -> tuple[str, ReceiverCaps]:
    """(label, capabilities) for a reported Cast model; baseline when unsure.

    ``manufacturer`` is accepted for callers' convenience but ignored: it is as
    spoofable as the model and must never widen what a receiver is sent.
    """
    text = _norm(model)
    for needle, label, caps in _PROFILES:
        if needle == text:
            return label, caps
    # Plain "Chromecast" (1st-3rd generation and ambiguous reports) is H.264 only.
    return "Google Cast receiver", CAST_BASELINE
