"""Casting session management: ffmpeg HLS transcode, direct play, device cast."""
from __future__ import annotations

import dataclasses
import ipaddress
import json
import logging
import math
import os
import pathlib
import platform
import re
import secrets
import socket
import subprocess
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import urlsplit
from fractions import Fraction
from http.client import HTTPConnection, HTTPException
from dataclasses import asdict, dataclass, field

from async_jobs import UserFacingError

import audio_downmix
import cache_policy
import cache_privacy
import ffmpeg_compat
import font_attachments
import castctl
import errors
import frozen_runtime
import hw_encoder_state
import hdr_tonemap
import lan_interfaces
import language_prefs
import loudness
import paths
import playback_state
import process_identity
import process_priority
import progress_model
import server as hls_server
import audio_delay
import subtitle_delay
import subtitle_encoding
import subtitle_style
import streamer_generation
import picture_adjustments
import video_policy
import aspect_override
import media_tools

ROOT = pathlib.Path.home() / ".cache/cast-control"
SERVER_SCRIPT = pathlib.Path(__file__).resolve().parent / "server.py"
# Plan (PLAN_FIRST): a `git pull` while a movie plays must not swap the HLS
# worker under the running parent. Launch the worker from a private snapshot of
# the launch generation (streamer_generation.freeze_worker), computed once.
_frozen_server_script: str | None = None


def _hls_server_script() -> str:
    """Worker path for the generation loaded at launch; frozen, else the live script."""
    global _frozen_server_script
    if _frozen_server_script is None:
        if frozen_runtime.is_frozen():
            _frozen_server_script = str(SERVER_SCRIPT)
        else:
            _frozen_server_script = str(
                streamer_generation.freeze_worker(SERVER_SCRIPT, ROOT))
    return _frozen_server_script
SESSION_FILE = ROOT / "session.json"
PROGRESS_FILE = ROOT / "progress.log"
FFMPEG_LOG = ROOT / "ffmpeg.log"
_ATTEMPT_LOG = logging.getLogger("smoothcast.attempts")
PORT = hls_server.PORT  # default; Session picks a free fallback if it is taken
FALLBACK_PORTS = 32  # PORT .. PORT+31 are scanned for a free port or our own server
HLS_NAME = "movie.m3u8"
SEGMENT_GLOB = "segment-*.ts"
HLS_SEGMENT_SECONDS = 4
HLS_PLAYLIST_SEGMENTS = 12
# Experimental #246 opt-in. Keep MPEG-TS default until receiver qualification.
HLS_SEGMENT_TYPE = os.environ.get("SMOOTHCAST_HLS_SEGMENT_TYPE", "mpegts").lower()
if HLS_SEGMENT_TYPE not in {"mpegts", "fmp4"}:
    HLS_SEGMENT_TYPE = "mpegts"
# A half-window margin avoids resuming into deleted live HLS segments.
HLS_PAUSE_RESTART_AFTER = HLS_SEGMENT_SECONDS * HLS_PLAYLIST_SEGMENTS / 2
_GENERATION_PLAYLIST = re.compile(r"movie-([0-9a-f]{32})(-fmp4)?\.m3u8\Z")


def _hls_names_from_url(url: str) -> tuple[str, str]:
    """Recover a safe exact-generation playlist and segment glob from a URL.

    Legacy fixed URLs can be recovered only while their old files exist;
    all newly encoded casts use distinct random resource names.
    """
    path = urlsplit(url).path
    if path == "/movie.m3u8":
        return HLS_NAME, SEGMENT_GLOB
    match = _GENERATION_PLAYLIST.fullmatch(path.removeprefix("/"))
    if not path.startswith("/") or not match:
        return "", ""
    token, fmp4 = match.groups()
    extension = "m4s" if fmp4 else "ts"
    suffix = "-fmp4" if fmp4 else ""
    return f"movie-{token}{suffix}.m3u8", f"segment-{token}-*.{extension}"


def _hls_init_from_url(url: str) -> str:
    """Return the generation-bound fMP4 initialization resource, if any."""
    match = _GENERATION_PLAYLIST.fullmatch(urlsplit(url).path.removeprefix("/"))
    return f"init-{match.group(1)}.mp4" if match and match.group(2) else ""


def _hls_output(generation: str) -> tuple[str, str, str, list[str]]:
    """Return private resource names and FFmpeg output args for one generation."""
    fmp4 = HLS_SEGMENT_TYPE == "fmp4"
    suffix = "-fmp4" if fmp4 else ""
    extension = "m4s" if fmp4 else "ts"
    playlist = f"movie-{generation}{suffix}.m3u8"
    pattern = f"segment-{generation}-*.{extension}"
    init = f"init-{generation}.mp4" if fmp4 else ""
    output_args = []
    if fmp4:
        output_args += ["-hls_segment_type", "fmp4",
                        "-hls_fmp4_init_filename", init]
    output_args += ["-hls_segment_filename",
                    str(ROOT / f"segment-{generation}-%05d.{extension}"),
                    str(ROOT / playlist)]
    return playlist, pattern, init, output_args


VAAPI_PATH = "/dev/dri/renderD128"
# 10-bit 4:2:0 is decoded on the GPU, converted to nv12 on the CPU, then
# encoded on the GPU: software x264 on a weak CPU cannot hold 1080p HEVC10 at
# real time. A GPU that cannot decode it stalls and takes the software retry.
VAAPI_PIX_FMTS = frozenset({"yuv420p", "nv12", "yuvj420p", "yuv420p10le", "p010le"})
VAAPI_TEN_BIT = frozenset({"yuv420p10le", "p010le"})

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts",
    ".mpeg", ".mpg", ".wmv", ".flv", ".ogv",
}
AUDIO_EXTS = {
    ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aiff", ".aif",
}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
DIRECT_EXTS = {".mp4", ".m4v", ".mov"}
DIRECT_VCODECS = {"h264"}
DIRECT_ACODECS = {"aac", "mp3"}
DIRECT_PIX_FMTS = {"yuv420p", "yuvj420p"}
SUBTITLE_EXTS = {".srt", ".vtt", ".ttml", ".ass", ".ssa"}
CAST_SUBTITLE_EXTS = {".srt", ".vtt", ".ttml"}
# FFmpeg's libass subtitles filter can decode these text formats. Bitmap
# tracks (PGS/VobSub/DVB) need a separate overlay path and must not be
# silently presented as supported text subtitles.
TEXT_SUBTITLE_CODECS = frozenset({"subrip", "ass", "ssa", "webvtt", "mov_text", "text", "sami"})
BITMAP_SUBTITLE_CODECS = frozenset({"dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle"})

QUALITY_QP = {"high": 20, "balanced": 24, "saver": 28}
QUALITY_LABELS = {
    "high": "High quality",
    "balanced": "Balanced quality",
    "saver": "Data saver",
}
QUALITY_DETAILS = {
    "high": "Best picture, most bandwidth (QP 20)",
    "balanced": "Everyday viewing (QP 24)",
    "saver": "Softer picture, lighter network use (QP 28)",
}

AUDIO_FILTERS = {
    "original": [],
    # Dialogue: a compressor does the real work — it pulls loud passages *down*
    # while leaving quiet speech untouched (so it can be lifted), which is what
    # stops action scenes from overwhelming dialogue. The limiter is a
    # transparent safety net. A loudness boost (audio_gain) is prepended so it
    # feeds the compressor instead of re-amplifying peaks afterwards. Unlike the
    # old dynaudnorm chain this adds no multi-second buffering, so audio stays in
    # sync with the video.
    "dialogue": [
        "acompressor=threshold=0.06:ratio=8:attack=20:release=250:makeup=1.8",
        "alimiter=limit=0.95:attack=5:release=80",
    ],
    # Night: stronger compression for low-volume late-night viewing.
    "night": [
        "acompressor=threshold=0.04:ratio=12:attack=25:release=300:makeup=2",
        "alimiter=limit=0.95:attack=5:release=80",
    ],
}

# Target mean loudness (dBFS) for auto input trim.  Sits well above the
# compressor thresholds (≈ -24 dB for dialogue, -28 dB for night) so the
# compressor is always engaging on average programme material.
_AUTO_TRIM_TARGET_DB = -16.0
_AUTO_TRIM_CLAMP_DB = (-12.0, 24.0)
AUDIO_LABELS = {
    "original": "Original audio",
    "dialogue": "Dialogue auto-fix",
    "night": "Night mode",
}
AUDIO_DETAILS = {
    "original": "Untouched soundtrack",
    "dialogue": "Compresses loud action and lifts quiet speech so dialogue stays audible",
    "night": "Stronger compression for late-night, low-volume viewing",
}


def audio_filters(profile: str, gain_db: float = 0.0,
                  loudness_mode: str = loudness.DEFAULT) -> list:
    """Return the ffmpeg -af chain for a profile, gain and loudness choice.

    ``gain_db`` is *prepended* so it feeds the compressor: positive values lift
    quiet dialogue above the compressor threshold, while negative values
    attenuate an over-loud soundtrack before compression. Both signs must be
    applied; dropping attenuation would leave a trimmed track too loud.
    ``original`` stays untouched and never gets gain. An explicit EBU R128
    loudness choice is appended last (after the limiter) for all profiles.
    """
    filters = list(AUDIO_FILTERS.get(profile) or [])
    if filters and gain_db is not None and float(gain_db) != 0:
        filters = [f"volume={float(gain_db):g}dB"] + filters
    filters += loudness.filter_args(loudness_mode)
    return filters


def state_loudness(state) -> str:
    """Loudness mode recorded on a session state, including older states."""
    if getattr(state, "music_autogain", False):
        return ("music_autogain_measured" if getattr(
            state, "music_autogain_measured", False) else "music_autogain")
    return getattr(state, "audio_loudness", loudness.DEFAULT) if state else loudness.DEFAULT


def music_hint_not_applied(hint: str, media, cfg: dict) -> str:
    enabled = (cfg.get("music_autogain", False)
               and loudness.normalize(cfg.get("audio_loudness", "off")) == loudness.DEFAULT)
    return hint + " · Music autogain not applied on this route" if (
        enabled and getattr(media, "is_audio_only", False)) else hint


def schedule_music_analysis(path, media, audio_track, owner, cfg) -> bool:
    """Schedule bounded analysis for this and the next queued audio track."""
    if not (cfg.get("music_autogain", False) and media.is_audio_only
            and loudness.normalize(cfg.get("audio_loudness", "off")) == loudness.DEFAULT):
        return False
    selected = preferred_audio_track(media, audio_track)
    track = selected.index if selected is not None else 0
    profile = cfg["audio"]
    filters = tuple(AUDIO_FILTERS.get(profile) or ())
    downmix = (audio_downmix.downmix_filter(selected.channels, selected.layout, profile)
               if selected is not None else None)
    loudness.schedule_analysis(path, track, profile, downmix=downmix, pre_filters=filters)
    choices = cfg.get("audio_track_by_file") or {}
    queued = tuple(getattr(owner, "queue", ()) or ())
    try:
        upcoming = queued[queued.index(str(path)) + 1:]
    except ValueError:
        upcoming = ()
    for candidate in upcoming:
        if pathlib.Path(candidate).suffix.lower() not in AUDIO_EXTS:
            continue
        choice = choices.get(candidate, -1) if isinstance(choices, dict) else -1
        next_track = choice if type(choice) is int and choice >= 0 else 0
        loudness.schedule_analysis(candidate, next_track, profile, pre_filters=filters)
        break
    return True


def monitor_summary(profile: str, gain_db: float,
                    loudness_mode: str = loudness.DEFAULT, *,
                    music_state=None) -> tuple[list, str]:
    """Metering chain and a concise hint for the current audio settings."""
    music_mode = loudness_mode in {"music_autogain", "music_autogain_measured"}
    measured = loudness_mode == "music_autogain_measured"
    if music_mode:
        loudness_mode = loudness.DEFAULT
    chain = audio_filters(profile, gain_db, loudness_mode)
    hint = AUDIO_LABELS.get(profile, profile)
    if gain_db > 0:
        hint += f" · +{gain_db:g} dB"
    if loudness.normalize(loudness_mode) != loudness.DEFAULT:
        hint += f" · {loudness.label(loudness_mode)}"
    if music_mode or getattr(music_state, "music_autogain", False):
        chain.append(loudness.music_filter(None))
        hint += " · Music autogain" + (
            " (measured)" if measured or getattr(music_state, "music_autogain_measured", False)
            else " (streaming fallback)")
    return chain, hint


def atempo_filters(speed: float) -> list:
    """Build one or more ffmpeg ``atempo`` filters for a playback speed.

    A single ``atempo`` only supports 0.5x–2.0x, so out-of-range speeds are
    achieved by chaining filters (each multiplies the rate).  Returns an empty
    list for normal 1.0x playback.
    """
    speed = max(0.05, float(speed))
    if speed == 1.0:
        return []
    filters: list = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:g}")
    return filters


_ROTATION_FILTERS = {
    0: [],
    90: ["transpose=1"],
    180: ["transpose=2,transpose=2"],
    270: ["transpose=2"],
}


def normalize_rotation(degrees) -> int:
    """Return a valid ffmpeg rotation (0/90/180/270 degrees clockwise), defaulting to 0."""
    try:
        degrees = int(degrees)
    except (TypeError, ValueError):
        return 0
    return degrees if degrees in _ROTATION_FILTERS else 0


def rotation_filters(degrees: int) -> list[str]:
    """ffmpeg ``-vf`` entries that rotate the video by *degrees* clockwise."""
    return list(_ROTATION_FILTERS.get(normalize_rotation(degrees), []))


_VOLUME_CACHE: "OrderedDict[tuple, float]" = OrderedDict()
_VOLUME_CACHE_LIMIT = 64
_VOLUME_LOCK = threading.Lock()


def _volume_cache_key(path: str, max_seconds: int, track: int,
                      downmix: str | None = None) -> tuple | None:
    """Identity of one measurement; None when the file cannot be identified.

    Size and mtime invalidate the entry when the film changes; the track and
    window are part of the key because each is a different measurement.
    """
    try:
        info = os.stat(path)
        return (os.path.realpath(path), info.st_size, info.st_mtime_ns, track, max_seconds, downmix)
    except OSError:
        return None


def measure_mean_volume(path: str, max_seconds: int = 60,
                        audio_track_index: int = 0,
                        downmix: str | None = None) -> float | None:
    """Quick volumedetect pass over the first *max_seconds* of one audio track.

    ``audio_track_index`` is the relative ``0:a:N`` stream, matching the track
    selected for the cast; measuring the default track would trim the wrong
    soundtrack. Skips video (``-vn``) so this is fast even for large files.
    Returns mean volume in dBFS, or ``None`` when the file has no audio stream
    or ffmpeg fails. Bounded by a 30-second timeout so a corrupt file cannot
    stall cast startup. ``downmix`` is an optional ``pan`` filter applied
    first, so the level is measured on the signal that will actually be sent.
    """
    track = (audio_track_index if type(audio_track_index) is int
             and audio_track_index >= 0 else 0)
    # Results are cached for the running app: a VAAPI-to-software retry and
    # every seek restart would otherwise repeat a pass that can take 30 s.
    # Only successful measurements are kept, so a transient failure or
    # timeout is retried rather than remembered.
    key = _volume_cache_key(path, max_seconds, track, downmix)
    if key is not None:
        with _VOLUME_LOCK:
            if key in _VOLUME_CACHE:
                _VOLUME_CACHE.move_to_end(key)
                return _VOLUME_CACHE[key]
    try:
        result = subprocess.run(
            [media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-i", path, "-map", f"0:a:{track}?",
             "-t", str(max_seconds), "-vn",
             "-af", ",".join([downmix, "volumedetect"] if downmix else ["volumedetect"]),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                value = float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except (ValueError, IndexError):
                continue
            if key is not None and math.isfinite(value):
                with _VOLUME_LOCK:
                    _VOLUME_CACHE[key] = value
                    while len(_VOLUME_CACHE) > _VOLUME_CACHE_LIMIT:
                        _VOLUME_CACHE.popitem(last=False)
            return value
    return None


def auto_trim_gain(path: str, profile: str, audio_track_index: int = 0,
                   downmix: str | None = None) -> float:
    """Return the dB gain needed so the compressor is always engaging.

    Measures the input's selected audio track and computes a trim that brings
    it to :data:`_AUTO_TRIM_TARGET_DB`, which sits above the compressor
    threshold so the compressor always has signal to work with.  Clamped to a
    sane range; the result can be negative for an over-loud track.  Returns
    ``0.0`` for the ``original`` profile or when measurement fails.
    """
    if profile == "original":
        return 0.0
    mean = (measure_mean_volume(path, audio_track_index=audio_track_index,
                                downmix=downmix) if downmix else
            measure_mean_volume(path, audio_track_index=audio_track_index))
    if mean is None:
        return 0.0
    lo, hi = _AUTO_TRIM_CLAMP_DB
    return max(lo, min(hi, _AUTO_TRIM_TARGET_DB - mean))


def effective_chain(path: str, profile: str, manual_gain_db: float = 0.0,
                    audio_track_index: int = 0,
                    loudness_mode: str = loudness.DEFAULT) -> list:
    """Full ffmpeg ``-af`` chain: auto trim, manual gain, profile and loudness.

    The auto-trim drives the signal above the compressor threshold so the
    compressor is always working; the manual gain adds on top for extra
    loudness (positive) or attenuation (negative). ``original`` normally has
    no chain and no measurement, but an explicit loudness choice still applies.
    """
    if profile == "original":
        return audio_filters(profile, loudness_mode=loudness_mode)
    trim = auto_trim_gain(path, profile, audio_track_index=audio_track_index)
    return audio_filters(profile, trim + manual_gain_db, loudness_mode)


class StreamError(RuntimeError):
    pass


class StreamPreparationError(StreamError, UserFacingError):
    """An expected playback preparation failure with copy safe to display."""


@dataclass(frozen=True)
class AudioTrack:
    """One audio stream, indexed relative to other audio tracks (0:a:N)."""
    index: int
    codec: str
    channels: int = 0
    language: str = ""
    title: str = ""
    layout: str = ""
    default: bool = False

    @property
    def label(self) -> str:
        parts = [self.language.upper() if self.language else "Undetermined"]
        if self.title:
            parts.append(self.title)
        parts.append(self.codec.upper() or "Unknown codec")
        if self.layout:
            parts.append(self.layout)
        elif self.channels:
            parts.append(f"{self.channels} channels")
        if self.default:
            parts.append("default")
        return " · ".join(parts)


def preferred_audio_track(media: "MediaInfo", requested: int = -1) -> AudioTrack | None:
    """Resolve a requested relative audio index, or default/first in auto mode."""
    if requested >= 0:
        return next((t for t in media.audio_streams if t.index == requested), None)
    chosen = language_prefs.choose_audio(media.audio_streams, language_prefs.load(media.path))
    if chosen is not None:
        return chosen
    return next((t for t in media.audio_streams if t.default), None) or (
        media.audio_streams[0] if media.audio_streams else None
    )


def media_summary(media: "MediaInfo") -> str:
    """Describe audio-only media without inventing a video resolution."""
    if media.is_audio_only:
        return " · ".join(bit for bit in (
            f"Audio · {media.acodec or 'unknown codec'}",
            f"{media.channels}ch" if media.channels else "",
        ) if bit)
    return " · ".join(bit for bit in (media.resolution, media.vcodec) if bit)


def audio_cast_options(media: "MediaInfo", subs_mode: str,
                       subs_path: pathlib.Path | None, burn: bool,
                       *, dlna: bool = False) -> tuple[pathlib.Path | None, bool]:
    """Resolve subtitle settings for audio-only media before receiver changes."""
    if getattr(media, "is_audio_only", False) is not True:
        return subs_path, burn
    if subs_mode in {"pick", "embedded"}:
        raise StreamPreparationError("Audio-only media does not support subtitles; choose Auto or Off", code="subtitle.audio_only")
    if dlna:
        raise StreamPreparationError("This DLNA receiver profile has not been verified for audio-only playback; choose a Google Cast target", code="cast.audio_only_unverified")
    return None, False


@dataclass(frozen=True)
class SubtitleTrack:
    """An embedded subtitle stream with a stream-relative FFmpeg si index."""
    index: int
    codec: str
    language: str = ""
    title: str = ""
    default: bool = False
    forced: bool = False

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_SUBTITLE_CODECS

    @property
    def is_bitmap(self) -> bool:
        return self.codec in BITMAP_SUBTITLE_CODECS

    @property
    def is_supported(self) -> bool:
        return self.is_text or self.is_bitmap

    @property
    def label(self) -> str:
        parts = [self.language.upper() if self.language else "Undetermined", self.title or self.codec]
        if self.forced:
            parts.append("forced")
        elif self.default:
            parts.append("default")
        if self.is_bitmap:
            parts.append("image track")
        elif not self.is_text:
            parts.append("unsupported subtitle format")
        return " · ".join(parts)


def preferred_embedded_subtitle(media: "MediaInfo", selected: int = -1) -> SubtitleTrack | None:
    """Select a supported text or bitmap track without guessing unknown formats."""
    if selected >= 0:
        return next((t for t in media.subtitle_tracks if t.index == selected and t.is_supported), None)
    supported = [t for t in media.subtitle_tracks if t.is_supported]
    if not supported:
        return None
    prefs = language_prefs.load(media.path)
    if prefs.subtitles:
        decision = language_prefs.choose_subtitle(supported, prefs, preferred_audio_track(media))
        if decision.decided:
            return decision.track
    return min(supported, key=lambda t: (
        not t.forced, not t.default, t.language.lower() not in {"en", "eng", "english"}, t.index
    ))


@dataclass(frozen=True)
class Chapter:
    """Source timeline chapter, independent from HLS stream offset."""
    start: float
    end: float
    title: str


MAX_CHAPTERS = 128


def _chapter_seconds(item: dict, field: str) -> float | None:
    try:
        ticks = item[field]
        if type(ticks) not in (str, int) or len(str(ticks)) > 24:
            raise ValueError("invalid chapter ticks")
        time_base = Fraction(str(item["time_base"]))
        if not 0 < time_base <= 1:
            raise ValueError("invalid time base")
        value = float(int(ticks) * time_base)
    except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        try:
            value = float(item[field + "_time"])
        except (KeyError, ValueError, TypeError, OverflowError):
            return None
    return value if math.isfinite(value) and 0 <= value <= 100_000_000 else None


def parse_chapters(value: object, duration: float = 0.0) -> tuple[Chapter, ...]:
    """Conservative flat-chapter parser; never invent an alternate edition map."""
    if not isinstance(value, list):
        return ()
    cap = duration if isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0 else None
    result: list[Chapter] = []
    for item in value[:MAX_CHAPTERS * 4]:
        if not isinstance(item, dict):
            continue
        start, end = _chapter_seconds(item, "start"), _chapter_seconds(item, "end")
        if start is None or end is None or end <= start:
            continue
        if cap is not None:
            if start >= cap:
                continue
            end = min(end, cap)
        if result and start < result[-1].end:
            continue  # Overlapping edition/segment markers are not safely seekable.
        tags = item.get("tags")
        raw_title = tags.get("title") if isinstance(tags, dict) else None
        title = " ".join(raw_title.split()) if isinstance(raw_title, str) else ""
        title = "".join(ch for ch in title if ch.isprintable())[:96]
        result.append(Chapter(start, end, title or f"Chapter {len(result) + 1}"))
        if len(result) >= MAX_CHAPTERS:
            break
    return tuple(result)


@dataclass
class MediaInfo:
    path: pathlib.Path
    duration: float = 0.0
    title: str = ""
    artist: str = ""
    album: str = ""
    track_number: int = 0
    disc_number: int = 0
    # FFprobe's absolute input stream index (not ordinal among video tracks).
    # Cover artwork can occupy stream 0, before the actual motion picture.
    video_stream_index: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    vprofile: str = ""
    pix_fmt: str = ""
    acodec: str = ""
    channels: int = 0
    audio_tracks: int = 0
    audio_streams: list[AudioTrack] = field(default_factory=list)
    subtitle_tracks: list[SubtitleTrack] = field(default_factory=list)
    chapters: tuple[Chapter, ...] = ()
    audio_only: bool = False
    size: int = 0
    bitrate: int = 0
    direct_ok: bool = False
    direct_reason: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""

    @property
    def has_video(self) -> bool:
        """Whether probe found a real motion-video stream (cover art is excluded)."""
        return bool(self.vcodec)

    @property
    def is_audio_only(self) -> bool:
        """Whether the file has audio but no motion-video stream."""
        return self.audio_only

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "unknown"

    @property
    def size_label(self) -> str:
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                if unit == "B":
                    return f"{value:.0f} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return ""

    @property
    def bitrate_label(self) -> str:
        if not self.bitrate:
            return ""
        return f"{self.bitrate / 1_000_000:.1f} Mbps"


def _usable_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return not (addr.is_loopback or addr.is_link_local or
                addr.is_unspecified or addr.is_multicast)


def _may_still_be_arriving(path: pathlib.Path) -> bool:
    """A guest upload may be cast while it is still arriving; only -readrate
    keeps FFmpeg behind the transfer, so such a file must not burst-read."""
    cache = os.environ.get("XDG_CACHE_HOME") or str(pathlib.Path.home() / ".cache")
    root = pathlib.Path(cache) / paths.APP_DIR / "portal-uploads"
    try:
        return pathlib.Path(path).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return True


def require_compatible_ffmpeg() -> tuple[int, int]:
    """Fail before changing active Cast ownership if HLS features are missing."""
    try:
        return ffmpeg_compat.require_supported_ffmpeg()
    except ffmpeg_compat.FFmpegVersionError as exc:
        raise StreamError(str(exc)) from exc


def host_ip(device_host: str | None = None) -> str:
    """Choose an outbound LAN IP, preferring the receiver's real route.

    A UDP connect only selects a source address; it sends no packet. If the
    route is unavailable (e.g. isolated LAN), enumerate private IPv4 interface
    addresses on Linux/macOS/Windows. No Linux-only hostname command.
    """
    if device_host and _usable_ipv4(device_host):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((device_host, 8009))
                candidate = sock.getsockname()[0]
            if _usable_ipv4(candidate):
                return candidate
        except OSError:
            pass

    candidate = lan_interfaces.select_private_lan_ip(device_host)
    if candidate:
        return candidate

    # The default route can work even if OS interface enumeration is denied.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        if _usable_ipv4(candidate):
            return candidate
    except OSError:
        pass

    raise StreamError(
        "No usable LAN IPv4 source address for streaming. "
        "Check that Wi-Fi/Ethernet is connected and the receiver is reachable "
        "on the selected network (interface enumeration and route probe failed)."
    )

_IS_WINDOWS = os.name == "nt"


def pid_alive(pid: int | None) -> bool:
    """Return True only if *pid* exists, without ever signalling it.

    ``os.kill(pid, 0)`` is an existence probe on POSIX, but on Windows
    ``os.kill`` maps to ``TerminateProcess`` for any signal, so probing a
    stale saved PID would kill an unrelated process. Windows therefore uses a
    query-only handle instead of ``os.kill``.
    """
    if not pid or pid <= 0:
        return False
    if _IS_WINDOWS:
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _pid_alive_windows(pid: int) -> bool:
    """Query whether *pid* is running without terminating it (Win32 only)."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
    except (ImportError, AttributeError):  # pragma: no cover - non-Windows
        return False
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_ours(pid: int | None, role: str, expected_start: float = 0.0) -> bool:
    """Do not adopt a reused saved PID, foreign user or different command."""
    if not pid or pid <= 1:
        return False
    if process_identity.psutil is not None:
        return process_identity.matches(
            process_identity.snapshot(pid), role,
            expected_start=expected_start if expected_start > 0 else None,
            server_script=str(SERVER_SCRIPT), progress_file=str(PROGRESS_FILE),
        )
    # Source-only Linux fallback permits read-only PID observation, never
    # signalling. Saved-session adoption requires an epoch birth time, which
    # /proc start ticks alone cannot validate without the original boot clock.
    if platform.system() != "Linux" or expected_start > 0 or not pid_alive(pid):
        return False
    try:
        argv = tuple(
            part.decode("utf-8", "replace")
            for part in pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if part
        )
    except OSError:
        return False
    return process_identity.role_of(
        argv, server_script=str(SERVER_SCRIPT), progress_file=str(PROGRESS_FILE),
    ) == role


def _terminate_pid(pid: int | None, role: str, expected_start: float = 0.0) -> None:
    """Never use os.kill on an unverified saved PID (especially on Windows)."""
    process_identity.stop_verified(
        pid, role, expected_start=expected_start if expected_start > 0 else None,
        server_script=str(SERVER_SCRIPT), progress_file=str(PROGRESS_FILE),
    )

class PidHandle:
    """Minimal Popen-like handle for verified processes restored from disk."""

    def __init__(self, pid: int, role: str, created_at: float = 0.0) -> None:
        self.pid = pid
        self.role = role
        self.created_at = created_at

    def poll(self) -> int | None:
        return None if _pid_is_ours(self.pid, self.role, self.created_at) else -1

    def terminate(self) -> None:
        _terminate_pid(self.pid, self.role, self.created_at)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("process did not exit")
            time.sleep(0.1)
        return 0


def _terminate(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _duration_seconds(raw: object) -> float:
    """Parse FFprobe format/stream duration, including MKV DURATION tags."""
    if raw is None:
        return 0.0
    try:
        value = str(raw).strip()
        if ":" in value:
            parts = value.split(":")
            if len(parts) != 3:
                return 0.0
            hours, minutes, seconds = map(float, parts)
            value_seconds = hours * 3600 + minutes * 60 + seconds
        else:
            value_seconds = float(value)
        return value_seconds if math.isfinite(value_seconds) and value_seconds > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _stream_duration(stream: dict) -> float:
    """Use ffprobe's seconds, Matroska duration tag, or exact time base."""
    duration = (_duration_seconds(stream.get("duration"))
                or _duration_seconds((stream.get("tags") or {}).get("DURATION")))
    if duration:
        return duration
    try:
        duration_ts = int(stream.get("duration_ts") or 0)
        time_base = Fraction(str(stream.get("time_base") or "0"))
        return _duration_seconds(float(duration_ts * time_base))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def _motion_video_stream(streams: list[dict]) -> dict | None:
    """Choose real motion video, never an attached/still cover image.

    Matroska can expose a one-frame MJPEG/PNG as an ordinary video stream
    *without* attached_pic. Dispositions alone therefore are insufficient;
    check frame count and per-stream duration too. Preserve the container's
    default-track choice among genuine video tracks.
    """
    candidates = []
    image_codecs = {"mjpeg", "png", "bmp", "gif", "webp", "tiff", "jpeg2000"}
    for position, stream in enumerate(streams):
        if stream.get("codec_type") != "video":
            continue
        disposition = stream.get("disposition") or {}
        if disposition.get("attached_pic") or disposition.get("still_image"):
            continue
        duration = (
            _duration_seconds(stream.get("duration"))
            or _duration_seconds((stream.get("tags") or {}).get("DURATION"))
        )
        raw_frames = stream.get("nb_frames")
        try:
            frames = int(raw_frames) if raw_frames is not None else 0
        except (ValueError, TypeError):
            frames = 0
        codec = str(stream.get("codec_name") or "").lower()
        if codec in image_codecs and (frames == 1 or 0 < duration < 0.5):
            continue
        candidates.append((bool(disposition.get("default")), duration,
                           codec not in image_codecs, -position, stream))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:4])[-1]


def _rotated_dimensions(width: int, height: int, rotation: int) -> tuple[int, int]:
    """Picture bounds after FFmpeg's transpose, before output scaling."""
    return (height, width) if rotation in (90, 270) else (width, height)


def _ffprobe_cancellable(args: list[str], cancel: threading.Event, timeout: float = 30):
    """Run FFprobe as a killable child for speculative queue metadata reads."""
    if cancel.is_set():
        raise StreamError("Next-item prewarm cancelled")
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except OSError as exc:
        raise StreamError(f"ffprobe could not be started: {exc}") from exc
    deadline = time.monotonic() + timeout
    while True:
        if cancel.is_set():
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.communicate()
            raise StreamError("Next-item prewarm cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            try:
                proc.kill()
            except OSError:
                pass
            proc.communicate()
            raise StreamPreparationError("ffprobe timed out while reading this file", code="media.probe_failed")
        try:
            stdout, stderr = proc.communicate(timeout=min(0.1, remaining))
            return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def ffprobe(path: pathlib.Path, *, cancel: threading.Event | None = None) -> MediaInfo:
    media = MediaInfo(path=path)
    try:
        media.size = path.stat().st_size
    except OSError:
        pass
    try:
        args = [media_tools.resolve_media_tool("ffprobe"), "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", "-show_chapters", str(path)]
        result = (_ffprobe_cancellable(args, cancel) if cancel is not None else
                  subprocess.run(args, capture_output=True, text=True, timeout=30))
    except FileNotFoundError as exc:
        raise StreamPreparationError("ffprobe is not installed or not on PATH", code="ffmpeg.probe_missing") from exc
    except subprocess.TimeoutExpired as exc:
        raise StreamPreparationError("ffprobe timed out while reading this file", code="media.probe_failed") from exc
    except OSError as exc:
        raise StreamError(f"ffprobe could not be started: {exc}") from exc
    if result.returncode != 0:
        raise StreamPreparationError("ffprobe could not read this file", code="media.probe_failed")
    try:
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            raise ValueError("ffprobe JSON is not an object")
        _read_probe(media, data)
    except (ValueError, TypeError, AttributeError, ArithmeticError, RecursionError) as exc:
        # ffprobe output is untrusted (damaged file, replaced binary): any
        # malformed shape is one clear error, never a crash in the GTK thread.
        raise StreamError("ffprobe returned unusable data for this file") from exc
    return media


def _read_probe(media: MediaInfo, data: dict) -> None:
    """Fill *media* from parsed ffprobe JSON; malformed shapes raise TypeError etc."""
    fmt = data.get("format") or {}
    media.duration = _duration_seconds(fmt.get("duration"))
    media.chapters = parse_chapters(data.get("chapters"), media.duration)
    tags = {str(key).casefold(): value for key, value in (fmt.get("tags") or {}).items()}
    media.title = str(tags.get("title") or "").strip()
    media.artist = str(tags.get("artist") or tags.get("album_artist") or "").strip()
    media.album = str(tags.get("album") or "").strip()

    def positive_tag(*names: str) -> int:
        for name in names:
            value = str(tags.get(name) or "").split("/", 1)[0].strip()
            try:
                number = int(value)
            except ValueError:
                continue
            if number > 0:
                return number
        return 0

    media.track_number = positive_tag("track", "tracknumber", "track_number")
    media.disc_number = positive_tag("disc", "discnumber", "disc_number") or 1
    try:
        media.bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        pass
    streams = data.get("streams") or []
    selected_video = _motion_video_stream(streams)
    subtitle_index = 0
    for stream_position, stream in enumerate(streams):
        kind = stream.get("codec_type")
        if kind == "video" and stream is selected_video:
            media.video_stream_index = int(stream.get("index", stream_position))
            media.vcodec = str(stream.get("codec_name") or "")
            media.vprofile = str(stream.get("profile") or "")
            media.pix_fmt = str(stream.get("pix_fmt") or "")
            media.color_transfer = str(stream.get("color_transfer") or "").lower()
            media.color_primaries = str(stream.get("color_primaries") or "").lower()
            media.color_space = str(stream.get("color_space") or "").lower()
            media.width = int(stream.get("width") or 0)
            media.height = int(stream.get("height") or 0)
            try:
                rate = float(Fraction(str(stream.get("avg_frame_rate") or "0")))
                media.fps = rate if math.isfinite(rate) and rate > 0 else 0.0
            except (ValueError, ZeroDivisionError, OverflowError):
                media.fps = 0.0
            if not media.duration:
                media.duration = _stream_duration(stream)
        elif kind == "audio":
            tags = stream.get("tags") or {}
            disposition = stream.get("disposition") or {}
            media.audio_streams.append(AudioTrack(
                index=media.audio_tracks,
                codec=str(stream.get("codec_name") or "").lower(),
                channels=int(stream.get("channels") or 0),
                language=str(tags.get("language") or ""),
                title=str(tags.get("title") or ""),
                layout=str(stream.get("channel_layout") or ""),
                default=bool(disposition.get("default")),
            ))
            media.audio_tracks += 1
            if not media.acodec:
                media.acodec = str(stream.get("codec_name") or "")
                media.channels = int(stream.get("channels") or 0)
            if not media.duration:
                media.duration = _stream_duration(stream)
        elif kind == "subtitle":
            tags = stream.get("tags") or {}
            disposition = stream.get("disposition") or {}
            media.subtitle_tracks.append(SubtitleTrack(
                index=subtitle_index,
                codec=str(stream.get("codec_name") or "").lower(),
                language=str(tags.get("language") or ""),
                title=str(tags.get("title") or ""),
                default=bool(disposition.get("default")),
                forced=bool(disposition.get("forced")),
            ))
            subtitle_index += 1
    media.audio_only = selected_video is None and bool(media.audio_streams)
    if not media.vcodec and not media.audio_streams:
        raise errors.coded(
            StreamError("No motion-video stream found (file may contain only cover artwork)"),
            "media.no_playable_stream")
    media.direct_ok, media.direct_reason = _direct_capable(media)


def _direct_capable(media: MediaInfo) -> tuple[bool, str]:
    if media.is_audio_only:
        return False, "Audio-only media uses the compatible AAC transcode path"
    if not media.has_video:
        return False, "No motion-video stream is available"
    if media.path.suffix.lower() not in DIRECT_EXTS:
        return False, f"{media.path.suffix or 'This format'} plays best through the transcoder"
    if media.vcodec not in DIRECT_VCODECS:
        return False, f"{media.vcodec or 'This'} video needs transcoding"
    if media.pix_fmt and media.pix_fmt not in DIRECT_PIX_FMTS:
        return False, f"{media.pix_fmt} colour needs transcoding"
    if media.acodec and media.acodec not in DIRECT_ACODECS:
        return False, f"{media.acodec or 'This'} audio needs transcoding"
    return True, "H.264/AAC plays directly with instant seeking"


def find_subtitles(path: pathlib.Path) -> pathlib.Path | None:
    """Find only this movie's sidecars, not similarly named films.

    Accept Film.srt, Film.en.srt, Film.forced.srt, Film.en.ass, etc.
    Reject Film2.srt for Film.mkv. Prefer SRT for receiver compatibility.
    """
    stem = path.stem.casefold()
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return None
    candidates = [
        entry for entry in entries if entry.is_file()
        and entry.suffix.lower() in SUBTITLE_EXTS
        and (entry.stem.casefold() == stem
             or entry.stem.casefold().startswith(stem + "."))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (
        entry.stem.casefold() != stem,
        entry.suffix.lower() not in CAST_SUBTITLE_EXTS,
        entry.suffix.lower() != ".srt",
        entry.name.casefold(),
    ))
    return candidates[0].resolve()


def valid_port(value: object) -> bool:
    return type(value) is int and 1024 <= value <= 65535


def configured_hls_port() -> int:
    """The ``hls_port`` setting if valid, else the default; never raises."""
    try:
        raw = json.loads(cache_policy.config_path().read_text())
        port = raw.get("hls_port") if isinstance(raw, dict) else None
    except (OSError, ValueError, RuntimeError):
        return PORT
    return port if valid_port(port) else PORT


def candidate_ports(preferred: int = PORT) -> list[int]:
    """Preferred port first, then the fallback range, without duplicates."""
    first = preferred if valid_port(preferred) else PORT
    return [first] + [p for p in range(PORT, PORT + FALLBACK_PORTS) if p != first]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _server_probe(port: int = PORT) -> tuple[bool, str | None, int | None]:
    """Return (healthy, listen address, pid) for the server on our port.

    The address and pid come from the health response. A recognised obsolete
    server deliberately reports no compatible bind address, so the next cast
    replaces it only after the usual process ownership checks.
    """
    connection = HTTPConnection("127.0.0.1", port, timeout=0.4)
    try:
        connection.request("GET", "/_smoothcast/health")
        response = connection.getresponse()
        if response.status != 200:
            return False, None, None
        body = response.read(64)
        if body not in (hls_server.HEALTH_BODY, b"SmoothCast HLS server v1\n"):
            return False, None, None
        pid = response.getheader("X-SmoothCast-Pid", "")
        bound = response.getheader("X-SmoothCast-Bind") if body == hls_server.HEALTH_BODY else None
        return True, bound, int(pid) if pid.isdigit() else None
    except (OSError, ValueError, HTTPException):
        return False, None, None
    finally:
        connection.close()


def _server_healthy(port: int = PORT) -> bool:
    """Verify our HLS server is listening; never mistake another app for it."""
    return _server_probe(port)[0]


@dataclass
class SessionState:
    file: str
    mode: str
    offset: float
    duration: float
    device: str
    title: str
    quality: str = "balanced"
    audio: str = "dialogue"
    audio_gain_db: float = 0.0
    audio_loudness: str = loudness.DEFAULT
    music_autogain: bool = False
    music_autogain_measured: bool = False
    audio_track_index: int = -1
    subs: str = ""
    burn_subs: bool = False
    embedded_subtitle_index: int = -1
    speed: float = 1.0
    rotation: int = 0
    started_at: float = 0.0
    ffmpeg_pid: int = 0
    server_pid: int = 0
    caster_pid: int = 0
    # OS process creation epoch times, distinct from session playback time.
    ffmpeg_created_at: float = 0.0
    server_created_at: float = 0.0
    caster_created_at: float = 0.0
    stream_url: str = ""
    subtitle_delay_ms: int = 0
    audio_delay_ms: int = 0
    aspect_mode: str = "original"


def load_session() -> SessionState | None:
    try:
        cache_privacy.ensure_private_directory(SESSION_FILE.parent)
        raw = json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    known = {k: v for k, v in raw.items() if k in SessionState.__dataclass_fields__}
    return _checked_state(known)


def _field_ok(value: object, expected: type) -> bool:
    if expected is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if expected is float:
        return isinstance(value, (int, float)) and math.isfinite(value)
    return isinstance(value, expected)


def _checked_state(known: dict) -> SessionState | None:
    """Build a SessionState from untrusted JSON, never trusting field types.

    A hand-edited or corrupt session.json (``"server_pid": []``) must not crash
    startup cleanup or process signalling. Required fields of the wrong type
    reject the whole file; optional ones fall back to their defaults.
    """
    clean: dict = {}
    for name, spec in SessionState.__dataclass_fields__.items():
        required = spec.default is dataclasses.MISSING
        expected = str if required and name not in ("offset", "duration") else (
            float if name in ("offset", "duration") else type(spec.default))
        if name in known and _field_ok(known[name], expected):
            clean[name] = known[name]
        elif required:
            return None
    if "aspect_mode" in clean:
        clean["aspect_mode"] = aspect_override.normalize(clean["aspect_mode"])
    try:
        return SessionState(**clean)
    except TypeError:
        return None


def _save_session(state: SessionState) -> None:
    cache_privacy.write_private_json_atomic(SESSION_FILE, asdict(state))


def clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)


class Session:
    """A live casting session: HLS transcode (or direct play) plus cast."""

    def __init__(self, port: int | None = None) -> None:
        # Preferred HLS port (the ``hls_port`` setting); the port actually in
        # use is whatever _start_server settles on and may be a fallback.
        self.port = port if port is not None and valid_port(port) else configured_hls_port()
        self.state: SessionState | None = None
        self.ffmpeg = None
        self.server = None
        self.caster = None
        # VAAPI requires Linux's /dev/dri. Windows/macOS use libx264 from
        # the first frame rather than stalling for 15 s on impossible VAAPI.
        self.used_software_fallback = platform.system() != "Linux"
        self._vaapi_stalled = False  # set only while retrying on software
        self.audio_chain: list = []
        # Progress and segment counts are read by background sampling so GTK
        # callbacks (seekbar/details) never touch the filesystem. The snapshot
        # belongs to this Session, so a retired session's values are never used
        # after the window swaps to a new one.
        self._snapshot_lock = threading.Lock()
        self._progress_snapshot = progress_model.EMPTY
        self._segments_snapshot = 0
        self._sampler_stop = threading.Event()
        self._sampler: threading.Thread | None = None
        # Private directory holding fonts extracted from the current source's
        # MKV attachments. Removed when the session stops or restarts.
        self._fonts_dir: pathlib.Path | None = None

    @property
    def mode(self) -> str:
        return self.state.mode if self.state else ""

    def restore(self, state: SessionState) -> None:
        self.state = state
        self._playlist_name, self._segment_pattern = _hls_names_from_url(
            state.stream_url if state.mode == "transcode" else "",
        )
        self._init_name = _hls_init_from_url(state.stream_url)
        self.audio_chain = audio_filters(
            state.audio, state.audio_gain_db, state.audio_loudness)
        def recovered(pid: int, role: str, created_at: float):
            if (type(created_at) not in (int, float)
                    or not math.isfinite(created_at) or created_at <= 0
                    or not _pid_is_ours(pid, role, created_at)):
                return None  # Old, malformed or reused PID: fail closed.
            return PidHandle(pid, role, created_at)

        self.ffmpeg = recovered(state.ffmpeg_pid, "encoder", state.ffmpeg_created_at)
        self.server = recovered(state.server_pid, "server", state.server_created_at)
        self.caster = recovered(state.caster_pid, "caster", state.caster_created_at)
        self._start_sampler()

    def active(self) -> bool:
        if self.mode == "direct":
            # catt may exit 0 immediately after instructing the Chromecast
            # to play. The cast keeps playing on the TV independently.
            # A successful direct session remains owned until stop/end.
            return self.state is not None
        if self.ffmpeg is not None and self.ffmpeg.poll() is None:
            return True
        return False

    def recoverable_hls(self) -> bool:
        """Completed local HLS media can outlive its encoder.

        This only proves the server has a finalized, readable playlist.
        The GUI must separately confirm that the receiver still reports
        our exact saved stream URL before reclaiming media ownership.
        """
        if self.mode != "transcode" or self.state is None:
            return False
        if self.ffmpeg is not None and self.ffmpeg.poll() is None:
            return False
        playlist, pattern = _hls_names_from_url(self.state.stream_url)
        if not playlist or not pattern:
            return False
        self._playlist_name, self._segment_pattern = playlist, pattern
        self._init_name = _hls_init_from_url(self.state.stream_url)
        return self._playlist_is_complete(ROOT / playlist) and _server_healthy()

    def encoder_finished(self) -> bool:
        if self.mode == "transcode":
            if self.ffmpeg is not None and self.ffmpeg.poll() is not None:
                return True
            return self.progress().done
        if self.mode == "direct":
            return self.caster is not None and self.caster.poll() is not None
        return False

    def progress(self) -> progress_model.Progress:
        """Return the last background progress snapshot (never reads disk)."""
        with self._snapshot_lock:
            return self._progress_snapshot

    def segment_count(self) -> int:
        """Return the last background segment count (never globs on the GTK thread)."""
        with self._snapshot_lock:
            return self._segments_snapshot

    def _read_progress(self, path=None) -> progress_model.Progress:
        progress_path = PROGRESS_FILE if path is None else path
        try:
            size = progress_path.stat().st_size
            with open(progress_path, "rb") as handle:
                handle.seek(max(0, size - 8192))
                tail = handle.read().decode("utf-8", "replace")
        except OSError:
            return progress_model.EMPTY
        return progress_model.parse_progress(tail)

    def _count_segments(self, root=None, pattern=None) -> int:
        segment_root = ROOT if root is None else root
        segment_pattern = SEGMENT_GLOB if pattern is None else pattern
        if not segment_pattern:
            # Older/invalid saved state has no verified HLS generation.
            # Never treat an empty glob as all media or crash background load.
            return 0
        try:
            return len(list(segment_root.glob(segment_pattern)))
        except OSError:
            return 0

    def _start_sampler(self) -> None:
        """Sample progress and segment count off the GTK thread."""
        self._stop_sampler()
        self._sampler_stop = threading.Event()
        # Bind the paths now so a session created inside a patched test
        # environment cannot later read the real cache.
        progress_path = PROGRESS_FILE
        root = ROOT
        pattern = getattr(self, "_segment_pattern", SEGMENT_GLOB)
        # Prime synchronously so the first UI tick already has data.
        progress = self._read_progress(progress_path)
        segments = self._count_segments(root, pattern)
        with self._snapshot_lock:
            self._progress_snapshot = progress
            self._segments_snapshot = segments

        def pump():
            while not self._sampler_stop.is_set():
                progress = self._read_progress(progress_path)
                segments = self._count_segments(root, pattern)
                with self._snapshot_lock:
                    self._progress_snapshot = progress
                    self._segments_snapshot = segments
                self._sampler_stop.wait(0.5)

        self._sampler = threading.Thread(target=pump, daemon=True)
        self._sampler.start()

    def _stop_sampler(self) -> None:
        self._sampler_stop.set()
        thread = self._sampler
        self._sampler = None
        if thread is not None:
            thread.join(timeout=1.0)

    _attempt = None  # per-attempt artifact folder for the encoder start in flight (#698)

    def _begin_attempt(self, args: list[str], software: bool) -> str:
        """Open an attempt folder (argv, plan reason); returns the plan reason. Never raises."""
        plan = "software encode" if software else "hardware encode (VAAPI), software fallback on stall"
        self._attempt = None
        try:
            import attempt_log
            self._attempt = attempt_log.begin(paths.cache_dir(), argv=[str(a) for a in args],
                                              plan_reason=plan)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never break a cast
            _ATTEMPT_LOG.warning("attempt diagnostics unavailable: %s", exc)
            self._attempt = None
        return plan

    def _end_attempt(self, outcome: str, reason: str = "") -> None:
        """Keep this attempt's ffmpeg stderr tail before a retry truncates ffmpeg.log."""
        attempt, self._attempt = self._attempt, None
        if attempt is None:
            return
        try:
            with open(FFMPEG_LOG, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 65536))
                attempt.write("ffmpeg.log", handle.read())
        except OSError as exc:
            _ATTEMPT_LOG.warning("could not keep ffmpeg stderr for this attempt: %s", exc)
        try:
            attempt.finish(outcome, reason)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never break a cast
            _ATTEMPT_LOG.warning("could not record attempt outcome: %s", exc)

    def log_tail(self, lines: int = 5) -> str:
        try:
            content = FFMPEG_LOG.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return " ".join(line.strip() for line in content[-lines:] if line.strip())

    def stop(self, device: str, *, send_stop: bool = True) -> bool:
        remote_stopped = False
        self._stop_sampler()
        _terminate(self.caster)
        _terminate(self.ffmpeg)
        _terminate(self.server)
        if self.state is not None:
            for pid, role, created in (
                (self.state.server_pid, "server", self.state.server_created_at),
                (self.state.ffmpeg_pid, "encoder", self.state.ffmpeg_created_at),
                (self.state.caster_pid, "caster", self.state.caster_created_at),
            ):
                if type(created) in (int, float) and math.isfinite(created) and created > 0:
                    _terminate_pid(pid, role, created)
        if send_stop:
            remote_stopped, _message = castctl.stop(device)
            remote_stopped = bool(remote_stopped)
        clear_session()
        # Revoke this session's generation so a kept-alive server stops
        # answering for a cast that has ended (#228) -- but only if the policy
        # still belongs to *this* session: stopping an older session after a
        # newer cast has started must not lock that cast's receiver out.
        match = _GENERATION_PLAYLIST.fullmatch(getattr(self, "_playlist_name", HLS_NAME))
        if match and hls_server.load_policy(ROOT).token == match.group(1):
            (ROOT / hls_server.POLICY_NAME).unlink(missing_ok=True)
        for segment in ROOT.glob(getattr(self, "_segment_pattern", SEGMENT_GLOB)):
            segment.unlink(missing_ok=True)
        init_name = getattr(self, "_init_name", "")
        if init_name and re.fullmatch(r"init-[0-9a-f]{32}\.mp4", init_name):
            (ROOT / init_name).unlink(missing_ok=True)
        playlist = getattr(self, "_playlist_name", HLS_NAME)
        if playlist == HLS_NAME or _GENERATION_PLAYLIST.fullmatch(playlist):
            (ROOT / playlist).unlink(missing_ok=True)
        for suffix in SUBTITLE_EXTS:
            (ROOT / f"burned_subs{suffix}").unlink(missing_ok=True)
        (ROOT / "receiver_subs.srt").unlink(missing_ok=True)
        font_attachments.cleanup_fonts(self._fonts_dir)
        self._fonts_dir = None
        self.state = None
        self.ffmpeg = None
        self.server = None
        self.caster = None
        return remote_stopped

    def _start_server(self, bind_ip: str | None = None,
                      receiver_ip: str | None = None, token: str = "") -> None:
        """Start (or reuse) the HLS server, reachable only by the receiver.

        The server listens on loopback plus *bind_ip* (never 0.0.0.0) and
        rejects other clients per the access policy published here before
        any reuse, so a server kept alive for a previous receiver follows the
        new one. A kept server bound to a different interface, or one that
        predates this restriction, is replaced only if its PID is verified
        as our own server; otherwise the cast is refused.
        """
        # CATT/yt-dlp probes the advertised HLS URL from this host's LAN IP.
        # Authorise that exact interface as well as the known receiver; do
        # not narrow the existing private-LAN fallback for unknown receivers.
        policy = hls_server.make_policy(receiver_ip, token=token)
        if bind_ip and not policy.any_private:
            policy = hls_server.make_policy(receiver_ip, extra=(bind_ip,), token=token)
        hls_server.write_policy(ROOT, policy)
        ports = candidate_ports(self.port)
        # Pass 1: reuse (or verifiably replace) a SmoothCast server that is
        # already listening on any candidate port, so a kept-alive server on a
        # fallback port is never orphaned when the preferred port frees up.
        busy = []
        for port in ports:
            if not _port_open(port):
                continue
            healthy, bound, pid = _server_probe(port)
            if not healthy:
                busy.append(port)         # another program owns it: leave it alone
                continue
            self.port = port
            if bound is not None and (bind_ip is None or bound == bind_ip):
                return  # Verified compatible server left alive by keep-streaming.
            if not _pid_is_ours(pid, "server"):
                raise StreamError(
                    f"A SmoothCast streaming server on port {port} is outdated or bound to a different "
                    "address and could not be verified for replacement; stop it and retry")
            _terminate_pid(pid, "server")
            if _port_open(port):
                raise errors.coded(StreamError(f"Port {port} is still in use by the previous streaming server"), "network.port_in_use")
            break
        else:
            # Pass 2: the first port nobody is listening on.
            free = next((p for p in ports if p not in busy), None)
            if free is None:
                raise StreamError(
                    f"Port {ports[0]} is already occupied by an unrecognised server and no "
                    f"fallback port in {PORT}-{PORT + FALLBACK_PORTS - 1} is free")
            self.port = free
        self.server = subprocess.Popen(
            frozen_runtime.server_command(pathlib.Path(_hls_server_script()))
            + ["--port", str(self.port)]
            + (["--bind", bind_ip] if bind_ip else []),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if self.server.poll() is not None:
                raise StreamError("The SmoothCast streaming server exited during startup")
            if _server_healthy(self.port):
                return
            time.sleep(0.1)
        _terminate(self.server)
        self.server = None
        raise StreamError("The SmoothCast streaming server did not become ready")

    def _stage_subs(
        self, subs_file: pathlib.Path | None, *, receiver: bool = False,
    ) -> pathlib.Path | None:
        """Stage owned caption bytes in the private cache, never user media.

        SRT is decoded and normalised to UTF-8 for both FFmpeg burn-in and
        Cast receiver subtitles; other formats retain their original bytes.
        A failed conversion never overwrites a previous valid staged file.
        """
        if subs_file is None:
            return None
        extension = subs_file.suffix.lower()
        if extension not in SUBTITLE_EXTS:
            raise StreamError(f"Unsupported subtitle file format: {extension or 'unknown'}")
        if receiver and extension != ".srt":
            raise StreamError("Only SRT supports receiver subtitle normalisation")
        cache_privacy.ensure_private_directory(ROOT)
        staged = ROOT / ("receiver_subs.srt" if receiver else f"burned_subs{extension}")
        if extension == ".srt":
            try:
                subtitle_encoding.stage_srt(subs_file, staged)
            except subtitle_encoding.SubtitleEncodingError as exc:
                raise StreamError(str(exc)) from exc
            return staged
        temporary = staged.with_name(f".{staged.name}.{os.getpid()}.tmp")
        try:
            size = subs_file.stat().st_size
            if size == 0 or size > 16 * 1024 * 1024:
                raise StreamError("Subtitle file must be between 1 byte and 16 MiB")
            # Keep all other staged subtitle formats private as well.
            with temporary.open("wb") as handle:
                os.chmod(temporary, 0o600)
                with subs_file.open("rb") as source:
                    data = source.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise StreamError("Subtitle file must be between 1 byte and 16 MiB")
                handle.write(data)
            temporary.replace(staged)
        except OSError as exc:
            raise StreamError(f"Could not stage subtitles: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return staged

    def _hw_state_path(self) -> pathlib.Path:
        return ROOT / hw_encoder_state.STATE_NAME

    def _vaapi_known_bad(self) -> bool:
        """A fresh, matching record says VAAPI stalled here before (#236)."""
        return hw_encoder_state.is_known_bad(
            self._hw_state_path(), hw_encoder_state.current_key(VAAPI_PATH))

    def _hwaccel_args(self, software: bool) -> list[str]:
        """Hardware decoder args — must come BEFORE -i (input options)."""
        if software:
            return []
        return [
            "-hwaccel", "vaapi", "-hwaccel_device", VAAPI_PATH,
            "-hwaccel_output_format", "vaapi",
        ]

    def _codec_args(self, quality: str, software: bool) -> list[str]:
        """Output video codec args — must come AFTER -i (output options)."""
        qp = QUALITY_QP.get(quality, 24)
        if software:
            # 8-bit 4:2:0 H.264/AAC is decodable by older Google Cast models.
            # Explicitly constrain output: a 10-bit HEVC/AV1 MKV must not
            # accidentally produce unsupported H.264 10-bit or 4:4:4 video.
            return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(qp + 1),
                    "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1"]
        return [
            "-c:v", "h264_vaapi", "-profile:v", "high", "-level:v", "4.1",
            "-qp", str(qp), "-g", "96",
        ]

    @staticmethod
    def _filter_path(path: pathlib.Path) -> str:
        """Escape a filename through FFmpeg filtergraph and option parsing.

        FFmpeg parses the filter graph and then the subtitle filter options,
        so ':' and apostrophes require additional quoting layers. Never pass
        untrusted filenames as interpolated shell command strings.
        """
        return (path.as_posix().replace("\\", "\\\\")
                .replace(":", "\\\\:").replace("'", "\\\\\\'")
                .replace(",", "\\,").replace(";", "\\;")
                .replace("[", "\\[").replace("]", "\\]"))

    def _filter_args(self, burn_subs: bool, staged: pathlib.Path | None, software: bool, speed: float, rotation: int = 0, *, aspect_mode: str = "original", embedded_subtitle_index: int | None = None, embedded_source: pathlib.Path | None = None, embedded_bitmap: bool = False, video_stream_index: int = 0, video_size: tuple[int, int] | None = None, subtitle_offset: float = 0.0, subtitle_delay_ms: int = 0, video_plan: video_policy.Plan | None = None, subtitle_force_style: str = "", fonts_dir: pathlib.Path | None = None, hdr_filter: str | None = None, quality: str = "balanced", source_fps: float = 0.0, picture_config: dict | None = None, ten_bit: bool = False) -> list[str]:
        chain: list[str] = []
        # H.264 High@4.1 is the conservative 1080p30 Cast baseline. Scale
        # alone does not make 1080p60/4K60 compatible with older receivers.
        # Adjust for the user's playback speed; leave 24/25/30fps unchanged.
        fps_cap = (math.isfinite(source_fps) and source_fps > 0
                   and source_fps * speed > 30.0)
        aspect_filters = aspect_override.filters(aspect_mode)
        # Optional auto deinterlace/crop (#54) run first, so captions are drawn on
        # the picture that is actually sent and every later size check sees it.
        plan_filters = video_plan.filters() if video_plan is not None else []
        if hdr_filter:
            # Tone-map the source before drawing any SDR caption overlays.
            plan_filters.append(hdr_filter)
        # Colour adjustments affect source pixels, not overlaid subtitle glyphs.
        # Include them in the hardware fallback decision below.
        plan_filters.extend(picture_adjustments.filters(picture_config))
        if plan_filters and video_size and video_plan is not None:
            video_size = video_plan.output_size(*video_size)
        chain.extend(plan_filters)
        if embedded_bitmap and embedded_subtitle_index is not None:
            # FFmpeg exposes bitmap subtitle rectangles as a temporary video
            # input to filter_complex. Keep this path on software frames; the
            # subtitle stream already carries its palette, geometry and timing.
            post_overlay = list(chain[len(plan_filters):])
            if speed != 1.0:
                post_overlay.append(f"setpts=PTS/{speed:g}")
            if fps_cap:
                post_overlay.append("fps=fps=30")
            post_overlay.extend(rotation_filters(rotation))
            post_overlay.extend(aspect_filters)
            if video_size and not aspect_filters:
                out_w, out_h = _rotated_dimensions(*video_size, rotation)
                if quality == "saver" and software and (out_w > 1280 or out_h > 720):
                    post_overlay.append(
                        "scale=w=1280:h=720:force_original_aspect_ratio=decrease:"
                        "force_divisible_by=2"
                    )
                elif out_w > 1920 or out_h > 1080:
                    post_overlay.append(
                        "scale=w=1920:h=1080:force_original_aspect_ratio=decrease:"
                        "force_divisible_by=2"
                    )
                elif out_w % 2 or out_h % 2:
                    post_overlay.append("scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2")
            video = f"[0:{video_stream_index}]"
            graph = ""
            if plan_filters:
                graph += f"{video}{','.join(plan_filters)}[picture];"
                video = "[picture]"
            delay = subtitle_delay.normalize(subtitle_delay_ms) / 1000
            graph += (f"[0:s:{embedded_subtitle_index}]setpts=PTS{delay:+g}/TB[bitmap];"
                      f"{video}[bitmap]overlay=eof_action=pass:repeatlast=0")
            if post_overlay:
                graph += f",{','.join(post_overlay)}"
            graph += "[v]"
            return ["-filter_complex", graph]
        sub_filter: str | None = None
        if embedded_subtitle_index is not None and embedded_source is not None:
            fonts = f":fontsdir='{self._filter_path(fonts_dir)}'" if fonts_dir else ""
            sub_filter = (f"subtitles=filename={self._filter_path(embedded_source)}"
                          f":si={embedded_subtitle_index}{fonts}{subtitle_force_style}")
        elif burn_subs and staged is not None:
            sub_filter = f"subtitles=filename={staged.name}{subtitle_force_style}"
        if sub_filter is not None:
            # libass sees encode-relative timestamps: re-add the -ss start and
            # apply the user delay, then restore the stream's own timeline.
            shift = subtitle_delay.filter_shift(subtitle_offset, subtitle_delay_ms)
            chain.extend([shift[0], sub_filter, shift[1]] if shift else [sub_filter])
        if speed != 1.0:
            chain.append(f"setpts=PTS/{speed:g}")
        if fps_cap:
            chain.append("fps=fps=30")
        chain.extend(rotation_filters(rotation))
        chain.extend(aspect_filters)
        # Scale the *transposed* picture. A 1920x1080 source rotated 90°
        # becomes 1080x1920; looking at input bounds alone missed this.
        # Both x264/yuv420p and h264_vaapi need even output dimensions.
        if video_size and ((quality == "saver" and software)
                           or (not aspect_filters and (software or rotation in (90, 270, 180)))):
            out_w, out_h = _rotated_dimensions(*video_size, rotation)
            if quality == "saver" and software and (out_w > 1280 or out_h > 720):
                chain.append(
                    "scale=w=1280:h=720:force_original_aspect_ratio=decrease:"
                    "force_divisible_by=2"
                )
            elif out_w > 1920 or out_h > 1080:
                chain.append(
                    "scale=w=1920:h=1080:force_original_aspect_ratio=decrease:"
                    "force_divisible_by=2"
                )
            elif out_w % 2 or out_h % 2:
                chain.append("scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2")
        # VAAPI keeps frames on GPU unless burning subtitles, so a rotation
        # filter (which runs in software) forces a download/upload round trip.
        need_subtitle_filter = ((burn_subs and staged is not None)
                                or embedded_subtitle_index is not None)
        force_software = not software and (
            ten_bit or rotation != 0 or bool(plan_filters) or bool(aspect_filters))
        if (not software and need_subtitle_filter) or force_software:
            # p010 surfaces must be converted before h264_vaapi sees them.
            head = "hwdownload,format=p010le,format=nv12" if ten_bit else "hwdownload,format=nv12"
            return ["-vf", ",".join([head, *chain, "hwupload"])]
        if chain:
            return ["-vf", ",".join(chain)]
        return []

    def start_transcode(
        self,
        media: MediaInfo,
        offset: float,
        *,
        device: str,
        quality: str,
        audio_profile: str,
        subs_file: pathlib.Path | None,
        burn_subs: bool,
        title: str,
        audio_gain_db: float = 0.0,
        audio_loudness: str = loudness.DEFAULT,
        device_ip: str | None = None,
        speed: float = 1.0,
        rotation: int = 0,
        aspect_mode: str = "original",
        embedded_subtitle_index: int | None = None,
        audio_track_index: int = -1,
        subtitle_delay_ms: int = 0,
        subtitle_preset: str = subtitle_style.DEFAULT,
        audio_delay_ms: int = 0,
        music_autogain: bool = False,
        picture_config: dict | None = None,
    ) -> None:
        if not device.strip():
            raise StreamError(castctl.NO_DEVICE_MESSAGE)
        # Fail before touching existing streaming resources or launching FFmpeg.
        require_compatible_ffmpeg()
        try:
            hdr_tonemap.require_available(media)
        except hdr_tonemap.TonemapUnavailable as exc:
            raise StreamError(str(exc)) from exc
        subtitle_delay_ms = subtitle_delay.normalize(subtitle_delay_ms)
        audio_delay_ms = audio_delay.normalize(audio_delay_ms)
        # Detect an unusable source address before spawning encoder/server jobs.
        local_ip = host_ip(device_ip)
        speed = max(0.05, float(speed))
        rotation = normalize_rotation(rotation)
        aspect_mode = aspect_override.normalize(aspect_mode)
        cache_privacy.ensure_private_directory(ROOT)
        # File names, not just query parameters, identify each encoder
        # generation: stale TV requests cannot read the replacement film.
        generation = secrets.token_hex(16)
        (self._playlist_name, self._segment_pattern, self._init_name,
         hls_output_args) = _hls_output(generation)
        PROGRESS_FILE.unlink(missing_ok=True)
        for segment in ROOT.glob(SEGMENT_GLOB):
            segment.unlink(missing_ok=True)
        for segment in ROOT.glob("segment-*.m4s"):
            if re.fullmatch(r"segment-[0-9a-f]{32}-[0-9]+\.m4s", segment.name):
                segment.unlink(missing_ok=True)
        for init in ROOT.glob("init-*.mp4"):
            if re.fullmatch(r"init-[0-9a-f]{32}\.mp4", init.name):
                init.unlink(missing_ok=True)
        # Remove only generated HLS playlists, not arbitrary cache content.
        for playlist in ROOT.glob("movie-*.m3u8"):
            if _GENERATION_PLAYLIST.fullmatch(playlist.name):
                playlist.unlink(missing_ok=True)
        (ROOT / HLS_NAME).unlink(missing_ok=True)
        audio_only = media.is_audio_only
        if audio_only and (subs_file is not None or embedded_subtitle_index is not None):
            raise StreamError("Audio-only media does not support subtitles")
        # Embedded text subtitles must be drawn by libass; the receiver
        # cannot decode Matroska subtitle tracks from a transcoded HLS stream.
        embedded_codec = ""
        bitmap_track = None
        if embedded_subtitle_index is not None:
            track = next((t for t in media.subtitle_tracks
                          if t.index == embedded_subtitle_index), None)
            if track is None or not track.is_supported:
                raise StreamPreparationError("Selected embedded subtitle track is unavailable or unsupported", code="subtitle.unavailable")
            bitmap_track = track if track.is_bitmap else None
            embedded_codec = track.codec if track.is_text else ""
            burn_subs = True
        # Explicit selections must fail before starting a new encoder. Keep
        # the optional audio map for silent videos with no audio streams.
        audio_track = preferred_audio_track(media, audio_track_index)
        if audio_track_index >= 0 and audio_track is None:
            raise StreamError(f"Audio track {audio_track_index + 1} is unavailable in this file")
        audio_map = f"0:a:{audio_track.index}" if audio_track is not None else "0:a:0?"
        staged = self._stage_subs(subs_file) if burn_subs and subs_file is not None else None
        receiver_subs = (
            self._stage_subs(subs_file, receiver=True)
            if not burn_subs and subs_file is not None and subs_file.suffix.lower() == ".srt"
            else subs_file
        )
        # The baseline Google Cast H.264 profile is capped at 1080p30; large
        # frames and high bit-depth/4:4:4 sources require a software downscale.
        video_plan = None
        if audio_only:
            # Audio-only HLS has no synthetic video stream and never invokes
            # VAAPI or the video policy planner.
            software = True
        else:
            video_plan = video_policy.make_plan(
                str(media.path), media.duration, media.width, media.height,
                video_stream=media.video_stream_index)
            out_w, out_h = _rotated_dimensions(*video_plan.output_size(media.width, media.height), rotation)
            if (out_w > 1920 or out_h > 1080 or hdr_tonemap.filter_for(media)
                    or (media.pix_fmt and media.pix_fmt not in VAAPI_PIX_FMTS)):
                self.used_software_fallback = True
        if bitmap_track is not None or picture_adjustments.active(picture_config):
            self.used_software_fallback = True
        if not audio_only and not self.used_software_fallback and self._vaapi_known_bad():
            # Skip a hardware start that already stalled on this exact setup.
            self.used_software_fallback = True
        software = True if audio_only else self.used_software_fallback
        args = [
            media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-loglevel", "warning",
            "-progress", str(PROGRESS_FILE), "-nostats",
            # Read source samples at the requested playback rate: a 2×
            # setpts/atempo stream needs 2× input, otherwise the TV starves.
            "-ss", str(max(0.0, offset)), "-readrate", f"{speed:g}",
        ]
        if not _may_still_be_arriving(media.path):
            # The first two segments no longer take 8 s of wall clock.
            args += ffmpeg_compat.initial_burst_args()
        if not audio_only:
            args += self._hwaccel_args(software)
        args += ["-i", str(media.path)]
        if audio_only:
            args += ["-vn"]
        elif bitmap_track is None:
            args += ["-map", f"0:{media.video_stream_index}"]
        args += ["-map", audio_map]
        if not audio_only:
            args += self._codec_args(quality, software)
        # Extract Matroska font attachments so embedded ASS/SSA styles keep
        # their intended typeface. Bitmap tracks are burned from their own
        # images and plain-text tracks carry no font references, so neither
        # needs the extraction. Replacing the previous session's directory
        # first keeps a failed restart from leaking its fonts.
        font_attachments.cleanup_fonts(self._fonts_dir)
        self._fonts_dir = None
        if bitmap_track is None and embedded_codec.lower() in {"ass", "ssa"}:
            self._fonts_dir = font_attachments.prepare_fonts(media.path, ROOT, generation)
        filter_args = [] if audio_only else self._filter_args(
            burn_subs, staged, software, speed, rotation, aspect_mode=aspect_mode,
            embedded_subtitle_index=embedded_subtitle_index,
            embedded_source=media.path if embedded_subtitle_index is not None else None,
            embedded_bitmap=bitmap_track is not None,
            video_stream_index=media.video_stream_index,
            video_size=(media.width, media.height),
            source_fps=media.fps,
            ten_bit=media.pix_fmt in VAAPI_TEN_BIT,
            quality=quality,
            subtitle_offset=max(0.0, offset),
            subtitle_delay_ms=subtitle_delay_ms,
            video_plan=video_plan,
            hdr_filter=hdr_tonemap.filter_for(media),
            picture_config=picture_config,
            subtitle_force_style=subtitle_style.force_style(
                subtitle_preset, codec=embedded_codec, path=staged) or "",
            fonts_dir=self._fonts_dir,
        )
        args += filter_args
        if filter_args[:1] == ["-filter_complex"]:
            args += ["-map", "[v]"]
        downmix = (audio_downmix.downmix_filter(audio_track.channels, audio_track.layout, audio_profile)
                   if audio_track is not None else None)
        profile_filters = AUDIO_FILTERS.get(audio_profile) or []
        music_autogain_active = (
            bool(music_autogain) and media.is_audio_only
            and loudness.normalize(audio_loudness) == loudness.DEFAULT
        )
        music_analysis = (loudness.get_cached(
            media.path, audio_track.index if audio_track is not None else 0,
            audio_profile, downmix=downmix, pre_filters=tuple(profile_filters),
        ) if music_autogain_active else None)
        if profile_filters and not music_autogain_active:
            # Auto-trim the selected soundtrack so the compressor always
            # engages, then apply the user's manual gain on top.  Store the
            # total so the monitor and resume paths use the exact same chain.
            trim = auto_trim_gain(
                str(media.path), audio_profile,
                audio_track_index=(audio_track.index if audio_track is not None else 0),
                downmix=downmix,
            )
            effective_gain = trim + audio_gain_db
        else:
            effective_gain = 0.0
        if music_autogain_active:
            filters = list(profile_filters)
            filters.append(loudness.music_filter(music_analysis))
        else:
            filters = audio_filters(audio_profile, effective_gain, audio_loudness)
        if downmix:
            filters = [downmix] + filters  # matrix first, then gain/compressor
        if speed != 1.0:
            # Change the playback/transcode rate: video timestamps are scaled
            # and audio is resampled with atempo so A/V stay in sync.
            filters += atempo_filters(speed)
        self.audio_chain = filters
        # Lip-sync delay last, after atempo, so it is measured in output time (#113).
        filters = filters + audio_delay.filters(audio_delay_ms)
        if filters:
            args += ["-af", ",".join(filters)]
        if not audio_only and media.fps > 30.01:
            args += ["-r", "30"]
        args += [
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-f", "hls", "-hls_time", str(HLS_SEGMENT_SECONDS),
            "-hls_list_size", str(HLS_PLAYLIST_SEGMENTS),
            "-hls_flags", "delete_segments+independent_segments",
        ]
        args += hls_output_args
        plan_reason = self._begin_attempt(args, software)
        with open(FFMPEG_LOG, "w") as log:
            # This encoder feeds the TV in real time; below 1x the receiver
            # buffers, so it keeps normal priority. At nice 10 a busy host
            # starved it to 0.5x (#686). Background conversions (DLNA,
            # previews) keep the #247 lower priority.
            low_priority = False
            self.ffmpeg = subprocess.Popen(
                args, cwd=str(ROOT),
                stdout=subprocess.DEVNULL, stderr=log,
                start_new_session=True,
                **process_priority.launch_kwargs(low_priority),
            )
            process_priority.lower(self.ffmpeg, low_priority)
        try:
            self._start_server(local_ip, device_ip, token=generation)
        except Exception as exc:  # noqa: BLE001 - record the attempt outcome, then re-raise
            self._end_attempt("failed", f"stream server did not start: {exc}")
            _terminate(self.ffmpeg)
            self.ffmpeg = None
            raise
        self._start_sampler()
        # Hardware FFmpeg can stall without exiting; a live PID isn't proof
        # that its VAAPI encoder is producing media. Retry once on software
        # after a bounded startup window, terminating the old encoder first.
        timeout = 15 if not software else 30
        if burn_subs or embedded_subtitle_index is not None:
            # libass must scan the whole source for fonts and cues before the
            # first frame; a large or cold MKV can exceed the plain window while
            # ffmpeg is healthy and silent (empty log).
            timeout *= 3
        if not self._wait_for_segments(timeout):
            tail = self.log_tail()
            self._end_attempt("stalled-retry-software" if not software else "failed",
                              f"no media segments within {timeout}s ({plan_reason})")
            if not software:
                _terminate(self.ffmpeg)
                self.ffmpeg = None
                self.used_software_fallback = True
                # Persist only if the software retry then succeeds: a broken
                # source must not get hardware encoding disabled.
                self._vaapi_stalled = True
                self.start_transcode(
                    media, offset, device=device, quality=quality,
                    audio_profile=audio_profile, subs_file=subs_file,
                    burn_subs=burn_subs, title=title,
                    audio_gain_db=audio_gain_db,
                    audio_loudness=audio_loudness, device_ip=device_ip,
                    speed=speed, rotation=rotation,
                    aspect_mode=aspect_mode,
                    embedded_subtitle_index=embedded_subtitle_index,
                    audio_track_index=audio_track_index,
                    subtitle_delay_ms=subtitle_delay_ms,
                    audio_delay_ms=audio_delay_ms,
                    music_autogain=music_autogain,
                )
                return
            raise errors.coded(StreamError(
                "the encoder failed to produce a stream within "
                f"{timeout}s ({plan_reason})" + (f" — {tail}" if tail else " — ffmpeg was silent (large source or subtitle burn-in?)")
            ), "ffmpeg.encoder_stalled")
        if self._vaapi_stalled:
            self._vaapi_stalled = False
            hw_encoder_state.record_failure(
                self._hw_state_path(), hw_encoder_state.current_key(VAAPI_PATH))
        url = f"http://{local_ip}:{self.port}/{self._playlist_name}"
        cast_args = ["-d", device, "cast", "--stream-type", "live", "-l", title, url]
        if not burn_subs and receiver_subs is not None and receiver_subs.suffix.lower() in CAST_SUBTITLE_EXTS:
            cast_args += ["-s", str(receiver_subs)]
        else:
            cast_args += ["--no-subs"]
        try:
            self.caster = subprocess.Popen(
                castctl.catt_command(cast_args),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True, text=True,
            )
            self._await_receiver(
                device,
                lambda info: playback_state.hls_session_matches(info, url, title),
            )
        except Exception as exc:  # noqa: BLE001 - record the attempt outcome, then re-raise
            self._end_attempt("failed", f"receiver did not accept the stream: {exc}")
            raise
        self.state = SessionState(
            file=str(media.path), mode="transcode", offset=max(0.0, offset),
            duration=media.duration, device=device, title=title, quality=quality,
            audio=audio_profile, audio_gain_db=effective_gain,
            audio_loudness=loudness.normalize(audio_loudness),
            music_autogain=music_autogain_active,
            music_autogain_measured=music_analysis is not None,
            audio_track_index=audio_track_index,
            subs=str(subs_file or ""), burn_subs=burn_subs,
            embedded_subtitle_index=(embedded_subtitle_index if embedded_subtitle_index is not None else -1),
            speed=speed,
            rotation=rotation,
            aspect_mode=aspect_mode,
            subtitle_delay_ms=subtitle_delay_ms,
            audio_delay_ms=audio_delay_ms,
            started_at=time.time(),
            ffmpeg_pid=getattr(self.ffmpeg, "pid", 0),
            server_pid=getattr(self.server, "pid", 0) if self.server else 0,
            caster_pid=getattr(self.caster, "pid", 0) if self.caster else 0,
            ffmpeg_created_at=process_identity.start_time(getattr(self.ffmpeg, "pid", 0)),
            server_created_at=process_identity.start_time(getattr(self.server, "pid", 0)),
            caster_created_at=process_identity.start_time(getattr(self.caster, "pid", 0)),
            stream_url=url,
        )
        _save_session(self.state)
        self._end_attempt("started", plan_reason)

    def _wait_for_segments(self, timeout: float, *, max_wait: float = 120.0) -> bool:
        # A busy CPU or subtitle burn-in can make a healthy encoder slower than
        # the initial window. While FFmpeg visibly advances, extend the wait
        # (bounded); a stalled encoder writes no progress and still times out.
        start = time.monotonic()
        deadline = start + timeout
        hard_cap = start + max(timeout, max_wait)
        last_progress: tuple[float, int | None] | None = None
        while time.monotonic() < deadline:
            try:
                current = self._read_progress()
                marker = (current.out_time, current.frame)
            except Exception:
                marker = None
            if marker is not None and marker != (0.0, None):
                if last_progress is not None and marker != last_progress:
                    deadline = max(deadline, min(hard_cap, time.monotonic() + 10.0))
                last_progress = marker
            playlist = ROOT / getattr(self, "_playlist_name", HLS_NAME)
            pattern = getattr(self, "_segment_pattern", SEGMENT_GLOB)
            if playlist.exists() and len(list(ROOT.glob(pattern))) >= 2:
                return True
            if self.ffmpeg is not None and self.ffmpeg.poll() is not None:
                # A two-second clip, or a seek into a film's final seconds, can
                # finalise with a single complete segment and then exit. Accept
                # that, but only for a successful encode whose finalised
                # playlist references segments that actually exist.
                return self.ffmpeg.returncode == 0 and self._playlist_is_complete(playlist)
            time.sleep(0.25)
        return False

    def _await_receiver(
        self, device: str, matches: Callable[[dict | None], bool], *,
        timeout: float = 40.0, interval: float = 0.25,
    ) -> None:
        """Confirm the receiver plays our media before a cast is treated as started.

        A fixed sleep cannot tell a successful cast from one that fails a moment
        later. Poll the receiver's own state until it reports our content, or a
        clear timeout; a catt process that exits non-zero fails immediately.
        """
        # catt itself allows up to 30 seconds for connection, plus discovery.
        # A 10-second confirmation deadline could kill a still-connecting load.
        deadline = time.monotonic() + timeout
        observed = False
        known_state = False
        last_status = {}
        silent_since: float | None = None
        resets = 0
        while True:
            if self.caster is not None and self.caster.poll() not in (None, 0):
                raise StreamPreparationError(
                    "Cast helper failed to start playback. Check the receiver connection.",
                    detail=self._caster_output("casting failed"), code="cast.command_failed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                info = castctl.info(device, timeout=min(8.0, remaining))
            except (OSError, ValueError, TypeError):
                info = None
            if isinstance(info, dict) and info:
                observed = True
                last_status = info
                known_state |= castctl.player_state(info) not in {"UNKNOWN", "OFFLINE"}
            if matches(info):
                return
            # A reply that never carries a playback state means the kept status
            # connection is stale (TV standby, app switch). Drop it so the next
            # read reconnects, instead of polling the same dead cache for 40 s.
            if known_state or not observed:
                silent_since = None
            else:
                now = time.monotonic()
                silent_since = now if silent_since is None else silent_since
                if now - silent_since >= 4.0 and resets < 3:
                    resets += 1
                    silent_since = now
                    try:
                        castctl.reset_status_route(device)
                    except Exception as exc:  # noqa: BLE001 - best-effort recovery only
                        castctl.log_backend_failure(f"status route reset failed: {exc}")
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
        if not observed:
            raise StreamPreparationError(
                "Receiver did not return status. Check its power, network and Cast connection.",
                detail=castctl.last_info_failure(device) or None,
                code="cast.receiver_offline")
        if not known_state:
            raise StreamPreparationError(
                "Receiver responded but did not report playback state. Check the TV's Cast app.",
                detail=f"Receiver app={last_status.get('app_id')!r}, "
                       f"state={castctl.player_state(last_status)}, "
                       f"media_present={bool(last_status.get('content_id'))}; "
                       f"{self._caster_output('helper still running or no output')}",
                code="cast.status_unavailable")
        raise StreamPreparationError(
            "Receiver is reachable but did not confirm playback of this media. Check the TV.",
            detail=self._caster_output("playback not confirmed"), code="cast.playback_unconfirmed")

    def _caster_output(self, fallback: str) -> str:
        """Best-effort catt output for an error; never block on a live catt."""
        output = ""
        try:
            if (self.caster is not None and self.caster.stdout is not None
                    and self.caster.poll() is not None):
                output = self.caster.stdout.read()
        except Exception:
            pass
        return (output or fallback).strip()[-300:]

    def _playlist_is_complete(self, playlist: pathlib.Path) -> bool:
        """True when a finalised playlist references only complete segments."""
        try:
            text = playlist.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if "#EXT-X-ENDLIST" not in text:
            return False
        names = [line.strip() for line in text.splitlines()
                 if line.strip() and not line.startswith("#")]
        if not names:
            return False
        for name in names:
            # Only files the HLS HTTP server is permitted to expose can
            # establish recoverability. Do not follow playlist traversal,
            # absolute paths or unrelated temporary files.
            playlist_name = getattr(self, "_playlist_name", HLS_NAME)
            if playlist_name == HLS_NAME:
                valid = re.fullmatch(r"segment-[0-9]+\.ts", name) is not None
            else:
                match = _GENERATION_PLAYLIST.fullmatch(playlist_name)
                if match and match.group(2):
                    init = f"init-{match.group(1)}.mp4"
                    if f'#EXT-X-MAP:URI="{init}"' not in text:
                        return False
                    try:
                        init_path = ROOT / init
                        if not init_path.is_file() or init_path.stat().st_size == 0:
                            return False
                    except OSError:
                        return False
                    valid = re.fullmatch(rf"segment-{match.group(1)}-[0-9]+\.m4s", name) is not None
                else:
                    valid = bool(match and re.fullmatch(
                        rf"segment-{match.group(1)}-[0-9]+\.ts", name,
                    ))
            if not valid:
                return False
            try:
                segment = ROOT / name
                if not segment.is_file() or segment.stat().st_size == 0:
                    return False
            except OSError:
                return False
        return True

    def start_direct(
        self,
        media: MediaInfo,
        *,
        device: str,
        subs_file: pathlib.Path | None,
        subs_disabled: bool,
        title: str,
        offset: float = 0.0,
    ) -> None:
        if not device.strip():
            raise StreamError(castctl.NO_DEVICE_MESSAGE)
        args = ["-d", device, "cast", "--stream-type", "buffered", "-l", title]
        if subs_disabled:
            args.append("--no-subs")
        elif subs_file is not None:
            receiver_subs = (
                self._stage_subs(subs_file, receiver=True)
                if subs_file.suffix.lower() == ".srt" else subs_file
            )
            args += ["-s", str(receiver_subs)]
        args.append(str(media.path))
        self.caster = subprocess.Popen(
            castctl.catt_command(args),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, text=True,
        )
        self._await_receiver(
            device,
            lambda info: playback_state.direct_session_matches(info, title),
        )
        # A previously watched file must resume on the TV, not merely report
        # its old position in the GUI. Fail the direct attempt if the receiver
        # cannot seek, so the caller can recover using an offset transcoder.
        offset = min(max(0.0, float(offset)), max(0.0, media.duration - 1.0)) if media.duration else max(0.0, float(offset))
        if offset > 0.0:
            ok, message = castctl.seek(device, offset)
            if not ok:
                raise StreamError(f"Direct resume seek failed: {message or 'receiver did not seek'}")
        self.state = SessionState(
            file=str(media.path), mode="direct", offset=offset,
            duration=media.duration, device=device, title=title,
            audio="original",
            subs=str(subs_file or ""), burn_subs=False,
            started_at=time.time(),
            caster_pid=getattr(self.caster, "pid", 0),
            caster_created_at=process_identity.start_time(getattr(self.caster, "pid", 0)),
        )
        _save_session(self.state)
