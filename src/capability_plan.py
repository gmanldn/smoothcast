"""Pure per-session compatibility plan from receiver capabilities (#11, SC-004).

Probe results go in (container/MIME, codecs, resolution, subtitle formats,
seek/Range support, playback speeds); an explicit plan comes out: direct, remux
or transcode, what is copied or re-encoded, how subtitles and seeking work and
a plain note for every decision. GTK-free, no I/O, no receiver commands.

Rule of thumb: an UNKNOWN capability (``None``) is never assumed to be
supported. Unknown cannot justify a direct send, so the plan falls back to the
conservative path and says so. ``prior_direct`` is advisory learned history (see
``receiver_memory``) and can only *remove* direct play, never add it where a
known capability forbids it.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Literal

Mode = Literal["direct", "remux", "transcode"]
SubtitlePlan = Literal["none", "sidecar", "burn_in"]
SeekPlan = Literal["native", "restart_at_offset"]

MAX_HEIGHT_CEILING = 8640
_TOKEN = re.compile(r"[a-z0-9_.+-]{1,48}\Z")
# MIME -> container it carries, for turning DLNA GetProtocolInfo into capabilities.
_MIME_CONTAINER = {
    "video/mp4": "mp4", "video/x-matroska": "mkv", "video/webm": "webm",
    "video/mpeg": "mpegts", "video/mp2t": "mpegts", "video/vnd.dlna.mpeg-tts": "mpegts",
    "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/flac": "flac", "audio/x-flac": "flac",
}


def _norm(values: Iterable[str] | None) -> frozenset[str] | None:
    """Lower-cased bounded tokens; ``None`` stays None (= unknown)."""
    if values is None:
        return None
    return frozenset(v.strip().lower() for v in values
                     if isinstance(v, str) and _TOKEN.fullmatch(v.strip().lower()))


@dataclass(frozen=True)
class ReceiverCaps:
    """What the receiver can take. ``None`` means unknown, never "everything"."""
    containers: frozenset[str] | None = None
    video_codecs: frozenset[str] | None = None
    audio_codecs: frozenset[str] | None = None
    subtitle_formats: frozenset[str] | None = None  # sidecar formats, e.g. {"vtt"}
    max_height: int | None = None
    hdr: bool | None = None
    seekable: bool | None = None  # supports byte-range / seek on a direct URL
    speeds: frozenset[float] = frozenset({1.0})

    @staticmethod
    def build(*, containers=None, video_codecs=None, audio_codecs=None,
              subtitle_formats=None, max_height=None, hdr=None, seekable=None,
              speeds=(1.0,)) -> "ReceiverCaps":
        height = max_height if type(max_height) is int and 0 < max_height <= MAX_HEIGHT_CEILING else None
        clean = frozenset(float(s) for s in speeds
                          if isinstance(s, (int, float)) and not isinstance(s, bool)
                          and math.isfinite(s) and 0.25 <= s <= 4.0) or frozenset({1.0})
        return ReceiverCaps(_norm(containers), _norm(video_codecs), _norm(audio_codecs),
                            _norm(subtitle_formats), height,
                            hdr if isinstance(hdr, bool) else None,
                            seekable if isinstance(seekable, bool) else None, clean)


# Only what every Google Cast receiver is documented to accept: a safe floor.
CAST_BASELINE = ReceiverCaps.build(
    containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac", "mp3"),
    subtitle_formats=("vtt",), max_height=1080, hdr=False, seekable=True)


def caps_from_http_formats(mimes: Iterable[str]) -> ReceiverCaps:
    """Containers implied by DLNA sink MIME types; codecs stay unknown (None)."""
    wanted = [str(x).strip().lower() for x in mimes]
    containers = {_MIME_CONTAINER[m] for m in wanted if m in _MIME_CONTAINER}
    if any(m in ("*", "video/*", "*/*") for m in wanted):
        containers |= {"mp4", "mpegts"}
    return ReceiverCaps.build(containers=containers or None)


@dataclass(frozen=True)
class MediaFacts:
    container: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    height: int = 0
    hdr: bool = False
    subtitle_kind: Literal["none", "sidecar", "embedded"] = "none"
    subtitle_format: str = ""  # of the sidecar, e.g. "srt"
    audio_only: bool = False


@dataclass(frozen=True)
class Request:
    """What the user asked for this session."""
    speed: float = 1.0
    rotation: int = 0
    needs_seek: bool = True
    audio_processing: bool = False  # downmix, gain, delay, picture adjustments...
    prior_direct: Literal["worked", "failed", None] = None


@dataclass(frozen=True)
class CompatPlan:
    mode: Mode
    video: Literal["copy", "encode", "none"]
    audio: Literal["copy", "encode", "none"]
    scale_to_height: int | None
    subtitles: SubtitlePlan
    seek: SeekPlan
    speed_native: bool
    conservative: bool  # True when an unknown capability forced the safe path
    notes: tuple[str, ...]


def _supports(known: frozenset[str] | None, value: str) -> bool | None:
    """True/False when known, None when the receiver capability is unknown."""
    if known is None:
        return None
    return value.strip().lower() in known


def plan_session(caps: ReceiverCaps, media: MediaFacts, request: Request = Request()) -> CompatPlan:
    notes: list[str] = []
    conservative = False
    encode_video = encode_audio = False
    scale: int | None = None

    speed = request.speed if isinstance(request.speed, (int, float)) and math.isfinite(request.speed) \
        and 0.25 <= request.speed <= 4.0 else 1.0
    speed_native = speed in caps.speeds
    if speed != 1.0 and not speed_native:
        encode_video = encode_audio = True
        notes.append(f"{speed:g}x speed is not supported by the receiver, so SmoothCast converts the stream.")
    if request.rotation % 360:
        encode_video = True
        notes.append("Rotation requires re-encoding the video.")
    if request.audio_processing:
        encode_audio = True
        notes.append("Audio adjustments require re-encoding the audio.")

    if not media.audio_only:
        verdict = _supports(caps.video_codecs, media.video_codec) if media.video_codec else False
        if verdict is not True:
            encode_video = True
            conservative |= verdict is None
            notes.append(f"Video ({media.video_codec or 'unknown'}) is "
                         + ("not confirmed playable on this receiver" if verdict is None
                            else "not supported by this receiver") + "; converting to H.264.")
        if caps.max_height and media.height > caps.max_height:
            encode_video, scale = True, caps.max_height
            notes.append(f"Resolution {media.height}p exceeds the receiver's {caps.max_height}p; scaling down.")
        if media.hdr and caps.hdr is not True:
            encode_video = True
            conservative |= caps.hdr is None
            notes.append("HDR is not confirmed on this receiver; tone-mapping to SDR.")
    verdict = _supports(caps.audio_codecs, media.audio_codec) if media.audio_codec else False
    if verdict is not True and media.audio_codec != "":
        encode_audio = True
        conservative |= verdict is None
        notes.append(f"Audio ({media.audio_codec}) is "
                     + ("not confirmed playable" if verdict is None else "not supported")
                     + " on this receiver; converting to AAC.")

    subtitles: SubtitlePlan = "none"
    if media.subtitle_kind == "sidecar":
        fmt = _supports(caps.subtitle_formats, media.subtitle_format)
        if fmt is True:
            subtitles = "sidecar"
        else:
            subtitles, encode_video = "burn_in", True
            conservative |= fmt is None
            notes.append("These subtitles are not confirmed on the receiver; burning them into the video.")
    elif media.subtitle_kind == "embedded":
        if _supports(caps.subtitle_formats, "embedded") is True:
            subtitles = "sidecar"
        else:
            subtitles, encode_video = "burn_in", True
            notes.append("Embedded subtitles cannot be sent separately; burning them into the video.")
    # A speaker (video codecs known to be empty) plays video files as audio only.
    drop_video = (not media.audio_only and caps.video_codecs is not None
                  and not caps.video_codecs and bool(media.video_codec))
    if drop_video:
        notes.append("This receiver is audio-only; sending just the soundtrack.")
    if media.audio_only or drop_video:
        encode_video, scale = False, None
        subtitles = "none"

    container = _supports(caps.containers, media.container) if media.container else False
    transform = encode_video or encode_audio
    if transform:
        mode: Mode = "transcode"
    elif drop_video:
        mode = "remux"
    elif container is True:
        mode = "direct"
    else:
        mode = "remux"
        conservative |= container is None
        notes.append(f"Container ({media.container or 'unknown'}) is "
                     + ("not confirmed" if container is None else "not supported")
                     + " on this receiver; repackaging without re-encoding.")

    if mode == "direct" and request.prior_direct == "failed":
        mode = "remux"
        notes.append("Direct play failed on this receiver before; using a repackaged stream.")
    if mode == "direct" and request.needs_seek and caps.seekable is not True:
        mode = "remux"
        conservative |= caps.seekable is None
        notes.append("Seeking on a direct URL is not confirmed for this receiver; using a seekable stream.")

    if mode == "direct" and request.prior_direct == "worked":
        notes.append("Direct play worked on this receiver before.")
    seek: SeekPlan = "native" if mode == "direct" else "restart_at_offset"
    return CompatPlan(
        mode=mode,
        video="none" if media.audio_only or drop_video else ("encode" if mode == "transcode" and encode_video else "copy"),
        audio=("none" if not media.audio_codec else
               "encode" if mode == "transcode" and encode_audio else "copy"),
        scale_to_height=scale if mode == "transcode" else None,
        subtitles=subtitles, seek=seek, speed_native=speed_native,
        conservative=conservative, notes=tuple(notes))
