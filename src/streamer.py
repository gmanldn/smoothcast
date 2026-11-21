"""Casting session management: ffmpeg HLS transcode, direct play, device cast."""
from __future__ import annotations

import dataclasses
import ipaddress
import json
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

import audio_downmix
import cache_policy
import cache_privacy
import ffmpeg_compat
import castctl
import frozen_runtime
import hw_encoder_state
import lan_interfaces
import language_prefs
import loudness
import playback_state
import process_identity
import process_priority
import progress_model
import server as hls_server
import audio_delay
import subtitle_delay
import subtitle_encoding
import subtitle_style
import video_policy

ROOT = pathlib.Path.home() / ".cache/cast-control"
SERVER_SCRIPT = pathlib.Path(__file__).resolve().parent / "server.py"
SESSION_FILE = ROOT / "session.json"
PROGRESS_FILE = ROOT / "progress.log"
FFMPEG_LOG = ROOT / "ffmpeg.log"
PORT = hls_server.PORT  # default; Session picks a free fallback if it is taken
FALLBACK_PORTS = 32  # PORT .. PORT+31 are scanned for a free port or our own server
HLS_NAME = "movie.m3u8"
SEGMENT_GLOB = "segment-*.ts"
HLS_SEGMENT_SECONDS = 4
HLS_PLAYLIST_SEGMENTS = 12
# A half-window margin avoids resuming into deleted live HLS segments.
HLS_PAUSE_RESTART_AFTER = HLS_SEGMENT_SECONDS * HLS_PLAYLIST_SEGMENTS / 2
_GENERATION_PLAYLIST = re.compile(r"movie-([0-9a-f]{32})\.m3u8\Z")


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
    token = match.group(1)
    return f"movie-{token}.m3u8", f"segment-{token}-*.ts"


VAAPI_PATH = "/dev/dri/renderD128"

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts",
    ".mpeg", ".mpg", ".wmv", ".flv", ".ogv",
}
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
    return getattr(state, "audio_loudness", loudness.DEFAULT) if state else loudness.DEFAULT


def monitor_summary(profile: str, gain_db: float,
                    loudness_mode: str = loudness.DEFAULT) -> tuple[list, str]:
    """Metering chain and a concise hint for the current audio settings."""
    chain = audio_filters(profile, gain_db, loudness_mode)
    hint = AUDIO_LABELS.get(profile, profile)
    if gain_db > 0:
        hint += f" · +{gain_db:g} dB"
    if loudness.normalize(loudness_mode) != loudness.DEFAULT:
        hint += f" · {loudness.label(loudness_mode)}"
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
            ["ffmpeg", "-hide_banner", "-i", path, "-map", f"0:a:{track}?",
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


@dataclass
class MediaInfo:
    path: pathlib.Path
    duration: float = 0.0
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
    size: int = 0
    bitrate: int = 0
    direct_ok: bool = False
    direct_reason: str = ""

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
        deadline = None if timeout is None else time.time() + timeout
        while self.poll() is None:
            if deadline is not None and time.time() > deadline:
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


def ffprobe(path: pathlib.Path) -> MediaInfo:
    media = MediaInfo(path=path)
    try:
        media.size = path.stat().st_size
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError as exc:
        raise StreamError("ffprobe is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise StreamError("ffprobe timed out while reading this file") from exc
    except OSError as exc:
        raise StreamError(f"ffprobe could not be started: {exc}") from exc
    if result.returncode != 0:
        raise StreamError("ffprobe could not read this file")
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
    try:
        media.bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        pass
    streams = data.get("streams") or []
    selected_video = _motion_video_stream(streams)
    if selected_video is None:
        raise StreamError("No motion-video stream found (file may contain only cover artwork)")
    subtitle_index = 0
    for stream_position, stream in enumerate(streams):
        kind = stream.get("codec_type")
        if kind == "video" and stream is selected_video:
            media.video_stream_index = int(stream.get("index", stream_position))
            media.vcodec = str(stream.get("codec_name") or "")
            media.vprofile = str(stream.get("profile") or "")
            media.pix_fmt = str(stream.get("pix_fmt") or "")
            media.width = int(stream.get("width") or 0)
            media.height = int(stream.get("height") or 0)
            try:
                rate = float(Fraction(str(stream.get("avg_frame_rate") or "0")))
                media.fps = rate if math.isfinite(rate) and rate > 0 else 0.0
            except (ValueError, ZeroDivisionError, OverflowError):
                media.fps = 0.0
            if not media.duration:
                media.duration = (
                    _duration_seconds(stream.get("duration"))
                    or _duration_seconds((stream.get("tags") or {}).get("DURATION"))
                )
                if not media.duration:
                    try:
                        duration_ts = int(stream.get("duration_ts") or 0)
                        time_base = Fraction(str(stream.get("time_base") or "0"))
                        media.duration = _duration_seconds(float(duration_ts * time_base))
                    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                        pass
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
    if not media.vcodec:
        raise StreamError("No motion-video stream found (file may contain only cover artwork)")
    media.direct_ok, media.direct_reason = _direct_capable(media)


def _direct_capable(media: MediaInfo) -> tuple[bool, str]:
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

    The address and pid come from headers added with the access restriction;
    an older server that predates them reports ``(True, None, None)``.
    """
    connection = HTTPConnection("127.0.0.1", port, timeout=0.4)
    try:
        connection.request("GET", "/_smoothcast/health")
        response = connection.getresponse()
        if response.status != 200 or response.read(64) != b"SmoothCast HLS server v1\n":
            return False, None, None
        pid = response.getheader("X-SmoothCast-Pid", "")
        return True, response.getheader("X-SmoothCast-Bind"), int(pid) if pid.isdigit() else None
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

    @property
    def mode(self) -> str:
        return self.state.mode if self.state else ""

    def restore(self, state: SessionState) -> None:
        self.state = state
        self._playlist_name, self._segment_pattern = _hls_names_from_url(
            state.stream_url if state.mode == "transcode" else "",
        )
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
        playlist = getattr(self, "_playlist_name", HLS_NAME)
        if playlist == HLS_NAME or _GENERATION_PLAYLIST.fullmatch(playlist):
            (ROOT / playlist).unlink(missing_ok=True)
        for suffix in SUBTITLE_EXTS:
            (ROOT / f"burned_subs{suffix}").unlink(missing_ok=True)
        (ROOT / "receiver_subs.srt").unlink(missing_ok=True)
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
        hls_server.write_policy(ROOT, hls_server.make_policy(receiver_ip, token=token))
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
            if bind_ip is None or bound == bind_ip:
                return  # Verified server left alive by keep-streaming.
            if not _pid_is_ours(pid, "server"):
                raise StreamError(
                    f"A SmoothCast streaming server on port {port} is bound to a different "
                    "address and could not be verified for replacement; stop it and retry")
            _terminate_pid(pid, "server")
            if _port_open(port):
                raise StreamError(f"Port {port} is still in use by the previous streaming server")
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
            frozen_runtime.server_command(SERVER_SCRIPT) + ["--port", str(self.port)]
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

    def _filter_args(self, burn_subs: bool, staged: pathlib.Path | None, software: bool, speed: float, rotation: int = 0, *, embedded_subtitle_index: int | None = None, embedded_source: pathlib.Path | None = None, embedded_bitmap: bool = False, video_stream_index: int = 0, video_size: tuple[int, int] | None = None, subtitle_offset: float = 0.0, subtitle_delay_ms: int = 0, video_plan: video_policy.Plan | None = None, subtitle_force_style: str = "") -> list[str]:
        chain: list[str] = []
        # Optional auto deinterlace/crop (#54) run first, so captions are drawn on
        # the picture that is actually sent and every later size check sees it.
        plan_filters = video_plan.filters() if video_plan is not None else []
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
            post_overlay.extend(rotation_filters(rotation))
            if video_size:
                out_w, out_h = _rotated_dimensions(*video_size, rotation)
                if out_w > 1920 or out_h > 1080:
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
            sub_filter = (f"subtitles=filename={self._filter_path(embedded_source)}"
                          f":si={embedded_subtitle_index}{subtitle_force_style}")
        elif burn_subs and staged is not None:
            sub_filter = f"subtitles=filename={staged.name}{subtitle_force_style}"
        if sub_filter is not None:
            # libass sees encode-relative timestamps: re-add the -ss start and
            # apply the user delay, then restore the stream's own timeline.
            shift = subtitle_delay.filter_shift(subtitle_offset, subtitle_delay_ms)
            chain.extend([shift[0], sub_filter, shift[1]] if shift else [sub_filter])
        if speed != 1.0:
            chain.append(f"setpts=PTS/{speed:g}")
        chain.extend(rotation_filters(rotation))
        # Scale the *transposed* picture. A 1920x1080 source rotated 90°
        # becomes 1080x1920; looking at input bounds alone missed this.
        # Both x264/yuv420p and h264_vaapi need even output dimensions.
        if video_size and (software or rotation in (90, 270, 180)):
            out_w, out_h = _rotated_dimensions(*video_size, rotation)
            if out_w > 1920 or out_h > 1080:
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
        force_software = not software and (rotation != 0 or bool(plan_filters))
        if (not software and need_subtitle_filter) or force_software:
            return ["-vf", f"hwdownload,format=nv12,{','.join(chain)},hwupload"]
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
        embedded_subtitle_index: int | None = None,
        audio_track_index: int = -1,
        subtitle_delay_ms: int = 0,
        subtitle_preset: str = subtitle_style.DEFAULT,
        audio_delay_ms: int = 0,
    ) -> None:
        if not device.strip():
            raise StreamError(castctl.NO_DEVICE_MESSAGE)
        # Fail before touching existing streaming resources or launching FFmpeg.
        require_compatible_ffmpeg()
        subtitle_delay_ms = subtitle_delay.normalize(subtitle_delay_ms)
        audio_delay_ms = audio_delay.normalize(audio_delay_ms)
        # Detect an unusable source address before spawning encoder/server jobs.
        local_ip = host_ip(device_ip)
        speed = max(0.05, float(speed))
        rotation = normalize_rotation(rotation)
        cache_privacy.ensure_private_directory(ROOT)
        # File names, not just query parameters, identify each encoder
        # generation: stale TV requests cannot read the replacement film.
        generation = secrets.token_hex(16)
        self._playlist_name = f"movie-{generation}.m3u8"
        self._segment_pattern = f"segment-{generation}-*.ts"
        PROGRESS_FILE.unlink(missing_ok=True)
        for segment in ROOT.glob(SEGMENT_GLOB):
            segment.unlink(missing_ok=True)
        # Remove only generated HLS playlists, not arbitrary cache content.
        for playlist in ROOT.glob("movie-*.m3u8"):
            if _GENERATION_PLAYLIST.fullmatch(playlist.name):
                playlist.unlink(missing_ok=True)
        (ROOT / HLS_NAME).unlink(missing_ok=True)
        # Embedded text subtitles must be drawn by libass; the receiver
        # cannot decode Matroska subtitle tracks from a transcoded HLS stream.
        embedded_codec = ""
        bitmap_track = None
        if embedded_subtitle_index is not None:
            track = next((t for t in media.subtitle_tracks
                          if t.index == embedded_subtitle_index), None)
            if track is None or not track.is_supported:
                raise StreamError("Selected embedded subtitle track is unavailable or unsupported")
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
        video_plan = video_policy.make_plan(
            str(media.path), media.duration, media.width, media.height,
            video_stream=media.video_stream_index)
        out_w, out_h = _rotated_dimensions(*video_plan.output_size(media.width, media.height), rotation)
        if (out_w > 1920 or out_h > 1080
                or (media.pix_fmt and media.pix_fmt not in {"yuv420p", "nv12", "yuvj420p"})):
            self.used_software_fallback = True
        if bitmap_track is not None:
            self.used_software_fallback = True
        if not self.used_software_fallback and self._vaapi_known_bad():
            # Skip a hardware start that already stalled on this exact setup.
            self.used_software_fallback = True
        software = self.used_software_fallback
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-progress", str(PROGRESS_FILE), "-nostats",
            # Read source samples at the requested playback rate: a 2×
            # setpts/atempo stream needs 2× input, otherwise the TV starves.
            "-ss", str(max(0.0, offset)), "-readrate", f"{speed:g}",
        ]
        args += self._hwaccel_args(software)
        args += ["-i", str(media.path)]
        if bitmap_track is None:
            args += ["-map", f"0:{media.video_stream_index}"]
        args += ["-map", audio_map]
        args += self._codec_args(quality, software)
        filter_args = self._filter_args(
            burn_subs, staged, software, speed, rotation,
            embedded_subtitle_index=embedded_subtitle_index,
            embedded_source=media.path if embedded_subtitle_index is not None else None,
            embedded_bitmap=bitmap_track is not None,
            video_stream_index=media.video_stream_index,
            video_size=(media.width, media.height),
            subtitle_offset=max(0.0, offset),
            subtitle_delay_ms=subtitle_delay_ms,
            video_plan=video_plan,
            subtitle_force_style=subtitle_style.force_style(
                subtitle_preset, codec=embedded_codec, path=staged) or "",
        )
        args += filter_args
        if filter_args[:1] == ["-filter_complex"]:
            args += ["-map", "[v]"]
        downmix = (audio_downmix.downmix_filter(audio_track.channels, audio_track.layout, audio_profile)
                   if audio_track is not None else None)
        profile_filters = AUDIO_FILTERS.get(audio_profile) or []
        if profile_filters:
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
        if media.fps > 30.01:
            args += ["-r", "30"]
        args += [
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-f", "hls", "-hls_time", str(HLS_SEGMENT_SECONDS),
            "-hls_list_size", str(HLS_PLAYLIST_SEGMENTS),
            "-hls_flags", "delete_segments+independent_segments",
            "-hls_segment_filename", str(ROOT / f"segment-{generation}-%05d.ts"),
            str(ROOT / self._playlist_name),
        ]
        with open(FFMPEG_LOG, "w") as log:
            low_priority = process_priority.enabled()
            self.ffmpeg = subprocess.Popen(
                args, cwd=str(ROOT),
                stdout=subprocess.DEVNULL, stderr=log,
                start_new_session=True,
                **process_priority.launch_kwargs(low_priority),
            )
            process_priority.lower(self.ffmpeg, low_priority)
        try:
            self._start_server(local_ip, device_ip, token=generation)
        except Exception:
            _terminate(self.ffmpeg)
            self.ffmpeg = None
            raise
        self._start_sampler()
        # Hardware FFmpeg can stall without exiting; a live PID isn't proof
        # that its VAAPI encoder is producing media. Retry once on software
        # after a bounded startup window, terminating the old encoder first.
        timeout = 15 if not software else 30
        if not self._wait_for_segments(timeout):
            tail = self.log_tail()
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
                    embedded_subtitle_index=embedded_subtitle_index,
                    audio_track_index=audio_track_index,
                    subtitle_delay_ms=subtitle_delay_ms,
                    audio_delay_ms=audio_delay_ms,
                )
                return
            raise StreamError("the encoder failed to produce a stream" + (f" — {tail}" if tail else ""))
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
        self.caster = subprocess.Popen(
            castctl.catt_command(cast_args),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, text=True,
        )
        self._await_receiver(
            device,
            lambda info: playback_state.hls_session_matches(info, url, title),
        )
        self.state = SessionState(
            file=str(media.path), mode="transcode", offset=max(0.0, offset),
            duration=media.duration, device=device, title=title, quality=quality,
            audio=audio_profile, audio_gain_db=effective_gain,
            audio_loudness=loudness.normalize(audio_loudness),
            audio_track_index=audio_track_index,
            subs=str(subs_file or ""), burn_subs=burn_subs,
            embedded_subtitle_index=(embedded_subtitle_index if embedded_subtitle_index is not None else -1),
            speed=speed,
            rotation=rotation,
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

    def _wait_for_segments(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
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
        timeout: float = 10.0, interval: float = 0.25,
    ) -> None:
        """Confirm the receiver plays our media before a cast is treated as started.

        A fixed sleep cannot tell a successful cast from one that fails a moment
        later. Poll the receiver's own state until it reports our content, or a
        clear timeout; a catt process that exits non-zero fails immediately.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.caster is not None and self.caster.poll() not in (None, 0):
                raise StreamError(self._caster_output("casting failed"))
            try:
                info = castctl.info(device)
            except (OSError, ValueError, TypeError):
                info = None
            if matches(info):
                return
            if time.monotonic() >= deadline:
                raise StreamError(self._caster_output(
                    "The receiver did not start playing this title in time"))
            time.sleep(interval)

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
