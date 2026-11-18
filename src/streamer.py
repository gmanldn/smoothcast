"""Casting session management: ffmpeg HLS transcode, direct play, device cast."""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field

import castctl

ROOT = pathlib.Path.home() / ".cache/cast-control"
SERVER_SCRIPT = pathlib.Path(__file__).resolve().parent / "server.py"
SESSION_FILE = ROOT / "session.json"
PROGRESS_FILE = ROOT / "progress.log"
FFMPEG_LOG = ROOT / "ffmpeg.log"
PORT = 8767
HLS_NAME = "movie.m3u8"
SEGMENT_GLOB = "segment-*.ts"
VAAPI_PATH = "/dev/dri/renderD128"

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts",
    ".mpeg", ".mpg", ".wmv", ".flv", ".ogv",
}
DIRECT_EXTS = {".mp4", ".m4v", ".mov"}
DIRECT_VCODECS = {"h264"}
DIRECT_ACODECS = {"aac", "mp3"}
DIRECT_PIX_FMTS = {"yuv420p", "yuvj420p"}
SUBTITLE_EXTS = {".srt", ".vtt", ".ttml"}

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


def audio_filters(profile: str, gain_db: float = 0.0) -> list:
    """Return the ffmpeg -af chain for a profile, with an optional loudness boost.

    ``gain_db`` is *prepended* so it feeds the compressor: quiet dialogue sits
    below the compressor threshold and receives the full boost, while loud
    passages are pushed further into compression and stay controlled instead of
    being re-amplified afterwards. ``original`` stays untouched and never gets
    gain.
    """
    filters = list(AUDIO_FILTERS.get(profile) or [])
    if not filters or gain_db is None or gain_db <= 0:
        return filters
    return [f"volume={float(gain_db):g}dB"] + filters


def measure_mean_volume(path: str, max_seconds: int = 60) -> float | None:
    """Quick volumedetect pass over the first *max_seconds* of audio.

    Skips video (``-vn``) so this is fast even for large files.  Returns mean
    volume in dBFS, or ``None`` when the file has no audio stream or ffmpeg
    fails.  Bounded by a 30-second timeout so a corrupt file cannot stall cast
    startup.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-map", "0:a:0?",
             "-t", str(max_seconds), "-vn", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except (ValueError, IndexError):
                pass
    return None


def auto_trim_gain(path: str, profile: str) -> float:
    """Return the dB gain needed so the compressor is always engaging.

    Measures the input's mean loudness and computes a trim that brings it to
    :data:`_AUTO_TRIM_TARGET_DB`, which sits above the compressor threshold so
    the compressor always has signal to work with.  Clamped to a sane range.
    Returns ``0.0`` for the ``original`` profile or when measurement fails.
    """
    if profile == "original":
        return 0.0
    mean = measure_mean_volume(path)
    if mean is None:
        return 0.0
    lo, hi = _AUTO_TRIM_CLAMP_DB
    return max(lo, min(hi, _AUTO_TRIM_TARGET_DB - mean))


def effective_chain(path: str, profile: str, manual_gain_db: float = 0.0) -> list:
    """Full ffmpeg ``-af`` chain: auto input trim + manual gain + profile filters.

    The auto-trim drives the signal above the compressor threshold so the
    compressor is always working; the manual gain adds on top for extra
    loudness.  For ``original`` the chain is empty and no measurement runs.
    """
    if profile == "original":
        return []
    trim = auto_trim_gain(path, profile)
    return audio_filters(profile, trim + manual_gain_db)


class StreamError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    path: pathlib.Path
    duration: float = 0.0
    width: int = 0
    height: int = 0
    vcodec: str = ""
    vprofile: str = ""
    pix_fmt: str = ""
    acodec: str = ""
    channels: int = 0
    audio_tracks: int = 0
    subtitle_tracks: list = field(default_factory=list)
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


def host_ip() -> str:
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, timeout=5).split()
        if out:
            return out[0]
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_pid(pid: int | None) -> None:
    if not pid_alive(pid):
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return
    for _ in range(20):
        if not pid_alive(pid):
            return
        time.sleep(0.15)
    try:
        os.kill(pid, 9)
    except OSError:
        pass


class PidHandle:
    """Minimal Popen-like handle for processes restored from disk."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return None if pid_alive(self.pid) else -1

    def terminate(self) -> None:
        _terminate_pid(self.pid)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.time() + timeout
        while pid_alive(self.pid):
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


def ffprobe(path: pathlib.Path) -> MediaInfo:
    media = MediaInfo(path=path)
    try:
        media.size = path.stat().st_size
    except OSError:
        pass
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise StreamError("ffprobe could not read this file")
    data = json.loads(result.stdout or "{}")
    fmt = data.get("format") or {}
    try:
        media.duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        pass
    try:
        media.bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        pass
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not media.vcodec:
            media.vcodec = str(stream.get("codec_name") or "")
            media.vprofile = str(stream.get("profile") or "")
            media.pix_fmt = str(stream.get("pix_fmt") or "")
            media.width = int(stream.get("width") or 0)
            media.height = int(stream.get("height") or 0)
            if not media.duration:
                try:
                    media.duration = float(stream.get("duration") or 0)
                except (TypeError, ValueError):
                    pass
        elif kind == "audio":
            media.audio_tracks += 1
            if not media.acodec:
                media.acodec = str(stream.get("codec_name") or "")
                media.channels = int(stream.get("channels") or 0)
        elif kind == "subtitle":
            tags = stream.get("tags") or {}
            label = tags.get("language") or tags.get("title") or stream.get("codec_name")
            media.subtitle_tracks.append(str(label))
    media.direct_ok, media.direct_reason = _direct_capable(media)
    return media


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
    stem = path.stem.lower()
    try:
        entries = sorted(path.parent.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.is_dir():
            continue
        if entry.stem.lower().startswith(stem) and entry.suffix.lower() in SUBTITLE_EXTS:
            return entry.resolve()
    return None


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


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
    subs: str = ""
    burn_subs: bool = False
    started_at: float = 0.0
    ffmpeg_pid: int = 0
    server_pid: int = 0
    caster_pid: int = 0
    stream_url: str = ""


def load_session() -> SessionState | None:
    try:
        raw = json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    known = {k: v for k, v in raw.items() if k in SessionState.__dataclass_fields__}
    try:
        return SessionState(**known)
    except TypeError:
        return None


def _save_session(state: SessionState) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state)))
    tmp.replace(SESSION_FILE)


def clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)


class Session:
    """A live casting session: HLS transcode (or direct play) plus cast."""

    def __init__(self) -> None:
        self.state: SessionState | None = None
        self.ffmpeg = None
        self.server = None
        self.caster = None
        self.used_software_fallback = False
        self.audio_chain: list = []

    @property
    def mode(self) -> str:
        return self.state.mode if self.state else ""

    def restore(self, state: SessionState) -> None:
        self.state = state
        self.audio_chain = audio_filters(state.audio, state.audio_gain_db)
        self.ffmpeg = PidHandle(state.ffmpeg_pid) if pid_alive(state.ffmpeg_pid) else None
        self.server = PidHandle(state.server_pid) if pid_alive(state.server_pid) else None
        self.caster = PidHandle(state.caster_pid) if pid_alive(state.caster_pid) else None

    def active(self) -> bool:
        if self.mode == "direct":
            return self.caster is not None and self.caster.poll() is None
        if self.ffmpeg is not None and self.ffmpeg.poll() is None:
            return True
        return False

    def encoder_finished(self) -> bool:
        if self.mode == "transcode":
            if self.ffmpeg is not None and self.ffmpeg.poll() is not None:
                return True
            return self.progress().get("progress") == "end"
        if self.mode == "direct":
            return self.caster is not None and self.caster.poll() is not None
        return False

    def progress(self) -> dict:
        out: dict = {}
        try:
            size = PROGRESS_FILE.stat().st_size
            with open(PROGRESS_FILE, "rb") as handle:
                handle.seek(max(0, size - 8192))
                tail = handle.read().decode("utf-8", "replace")
        except OSError:
            return out
        for line in tail.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
        try:
            us = float(out.get("out_time_us") or 0)
            out["out_time"] = us / 1_000_000 if us else float(out.get("out_time_ms") or 0) / 1_000_000
        except ValueError:
            out["out_time"] = 0.0
        return out

    def log_tail(self, lines: int = 5) -> str:
        try:
            content = FFMPEG_LOG.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return " ".join(line.strip() for line in content[-lines:] if line.strip())

    def stop(self, device: str, *, send_stop: bool = True) -> None:
        _terminate(self.caster)
        _terminate(self.ffmpeg)
        _terminate(self.server)
        if self.state is not None:
            for pid in (self.state.server_pid, self.state.ffmpeg_pid, self.state.caster_pid):
                _terminate_pid(pid)
        if send_stop:
            castctl.stop(device)
        clear_session()
        for segment in ROOT.glob(SEGMENT_GLOB):
            segment.unlink(missing_ok=True)
        self.state = None
        self.ffmpeg = None
        self.server = None
        self.caster = None

    def _start_server(self) -> None:
        if _port_open(PORT):
            return
        self.server = subprocess.Popen(
            ["python3", str(SERVER_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if _port_open(PORT):
                return
            time.sleep(0.1)

    def _stage_subs(self, subs_file: pathlib.Path | None) -> pathlib.Path | None:
        if subs_file is None:
            return None
        staged = ROOT / f"burned_subs{subs_file.suffix.lower()}"
        try:
            staged.write_bytes(subs_file.read_bytes())
        except OSError:
            raise StreamError("could not stage the subtitles file")
        return staged

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
            return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(qp + 1)]
        return [
            "-c:v", "h264_vaapi", "-profile:v", "high", "-level:v", "4.1",
            "-qp", str(qp), "-g", "96",
        ]

    def _filter_args(self, burn_subs: bool, staged: pathlib.Path | None, software: bool) -> list[str]:
        chain: list[str] = []
        if burn_subs and staged is not None:
            chain.append(f"subtitles=filename={staged.name}")
        if not software and burn_subs and staged is not None:
            # Only download/upload when burning subtitles; otherwise frames
            # stay in GPU memory and the VAAPI encoder handles them directly.
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
    ) -> None:
        ROOT.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.unlink(missing_ok=True)
        for segment in ROOT.glob(SEGMENT_GLOB):
            segment.unlink(missing_ok=True)
        (ROOT / HLS_NAME).unlink(missing_ok=True)
        staged = self._stage_subs(subs_file) if burn_subs else None
        software = self.used_software_fallback
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-progress", str(PROGRESS_FILE), "-nostats",
            "-ss", str(max(0.0, offset)), "-re",
        ]
        args += self._hwaccel_args(software)
        args += ["-i", str(media.path), "-map", "0:v:0", "-map", "0:a:0?"]
        args += self._codec_args(quality, software)
        args += self._filter_args(burn_subs, staged, software)
        filters = audio_filters(audio_profile, audio_gain_db)
        if filters:
            # Auto-trim the input so the compressor always engages, then apply
            # the user's manual gain on top.  Store the total so the monitor
            # and resume paths use the exact same chain.
            trim = auto_trim_gain(str(media.path), audio_profile)
            effective_gain = trim + audio_gain_db
            filters = audio_filters(audio_profile, effective_gain)
        else:
            effective_gain = 0.0
        self.audio_chain = filters
        if filters:
            args += ["-af", ",".join(filters)]
        args += [
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "12",
            "-hls_flags", "delete_segments+independent_segments",
            "-hls_segment_filename", str(ROOT / "segment-%05d.ts"),
            str(ROOT / HLS_NAME),
        ]
        with open(FFMPEG_LOG, "w") as log:
            self.ffmpeg = subprocess.Popen(
                args, cwd=str(ROOT),
                stdout=subprocess.DEVNULL, stderr=log,
                start_new_session=True,
            )
        self._start_server()
        if not self._wait_for_segments(30):
            if self.ffmpeg.poll() is not None and not self.used_software_fallback:
                self.used_software_fallback = True
                self.start_transcode(
                    media, offset, device=device, quality=quality,
                    audio_profile=audio_profile, subs_file=subs_file,
                    burn_subs=burn_subs, title=title,
                    audio_gain_db=audio_gain_db,
                )
                return
            tail = self.log_tail()
            raise StreamError("the encoder failed to produce a stream" + (f" — {tail}" if tail else ""))
        url = f"http://{host_ip()}:{PORT}/{HLS_NAME}"
        cast_args = ["-d", device, "cast", "--stream-type", "live", "-l", title, url]
        if subs_file is not None:
            cast_args += ["-s", str(subs_file)]
        else:
            cast_args += ["--no-subs"]
        self.caster = subprocess.Popen(
            [str(castctl.CATT), *cast_args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, text=True,
        )
        time.sleep(2.0)
        if self.caster.poll() not in (None, 0):
            output = ""
            try:
                output = self.caster.stdout.read() if self.caster.stdout else ""
            except Exception:
                pass
            raise StreamError((output or "casting failed").strip()[-300:])
        self.state = SessionState(
            file=str(media.path), mode="transcode", offset=max(0.0, offset),
            duration=media.duration, device=device, title=title, quality=quality,
            audio=audio_profile, audio_gain_db=effective_gain,
            subs=str(subs_file or ""), burn_subs=burn_subs,
            started_at=time.time(),
            ffmpeg_pid=getattr(self.ffmpeg, "pid", 0),
            server_pid=getattr(self.server, "pid", 0) if self.server else 0,
            caster_pid=getattr(self.caster, "pid", 0) if self.caster else 0,
            stream_url=url,
        )
        _save_session(self.state)

    def _wait_for_segments(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ffmpeg is not None and self.ffmpeg.poll() is not None:
                return False
            segments = list(ROOT.glob(SEGMENT_GLOB))
            if (ROOT / HLS_NAME).exists() and len(segments) >= 2:
                return True
            time.sleep(0.25)
        return False

    def start_direct(
        self,
        media: MediaInfo,
        *,
        device: str,
        subs_file: pathlib.Path | None,
        subs_disabled: bool,
        title: str,
    ) -> None:
        args = ["-d", device, "cast", "--stream-type", "buffered", "-l", title]
        if subs_disabled:
            args.append("--no-subs")
        elif subs_file is not None:
            args += ["-s", str(subs_file)]
        args.append(str(media.path))
        self.caster = subprocess.Popen(
            [str(castctl.CATT), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, text=True,
        )
        time.sleep(2.5)
        if self.caster.poll() is not None and self.caster.returncode != 0:
            output = ""
            try:
                output = self.caster.stdout.read() if self.caster.stdout else ""
            except Exception:
                pass
            raise StreamError((output or "direct play failed").strip()[-300:])
        self.state = SessionState(
            file=str(media.path), mode="direct", offset=0.0,
            duration=media.duration, device=device, title=title,
            subs=str(subs_file or ""), burn_subs=False,
            started_at=time.time(),
            caster_pid=getattr(self.caster, "pid", 0),
        )
        _save_session(self.state)
