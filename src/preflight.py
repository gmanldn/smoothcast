"""Bounded local FFmpeg decoder preflight, without touching the Cast receiver.

A short private H.264/AAC sample validates source decoders, chosen audio
stream and requested burned subtitles before replacing any active TV session.
All temporary media is removed after the check.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib
import subprocess
import tempfile
from typing import TYPE_CHECKING

from async_jobs import UserFacingError

import subtitle_encoding

if TYPE_CHECKING:
    import streamer


class PreflightError(UserFacingError):
    """Cannot safely decode the requested source/transforms."""


@dataclass(frozen=True)
class PreflightResult:
    bytes_rendered: int
    sample_seconds: float


def _filter_path(path: pathlib.Path) -> str:
    """FFmpeg option/graph escaping; never create a shell command."""
    return (path.as_posix().replace("\\", "\\\\")
            .replace(":", "\\\\:").replace("'", "\\\\\\'")
            .replace(",", "\\,").replace(";", "\\;")
            .replace("[", "\\[").replace("]", "\\]"))


def check_media(
    media: "streamer.MediaInfo",
    *,
    audio_track_index: int = -1,
    subs_file: pathlib.Path | None = None,
    burn_subs: bool = False,
    embedded_subtitle_index: int | None = None,
    timeout: float = 20,
) -> PreflightResult:
    """Render a private 0.8 s Matroska sample; fail before controlling a TV.

    This is a CPU software decode/encode check, not a hardware or TV
    certification. It validates an explicit audio/subtitle selection and the
    FFmpeg/libass subtitle filter when burn-in is required.
    """
    path = pathlib.Path(media.path)
    if not path.is_file():
        raise PreflightError("The selected movie no longer exists")
    if media.is_audio_only:
        if subs_file is not None or embedded_subtitle_index is not None or burn_subs:
            raise PreflightError("Audio-only media does not support subtitles")
        tracks = media.audio_streams
        if audio_track_index >= 0 and not any(t.index == audio_track_index for t in tracks):
            raise PreflightError("The selected audio track is not in this file")
        selected = next((t for t in tracks if t.index == audio_track_index), None) if audio_track_index >= 0 else None
        selected = selected or next((t for t in tracks if t.default), None) or (tracks[0] if tracks else None)
        if selected is None:
            raise PreflightError("The selected file has no audio stream")
        with tempfile.TemporaryDirectory(prefix="smoothcast-preflight-") as folder:
            output = pathlib.Path(folder) / "sample.mka"
            args = [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(path), "-map", f"0:a:{selected.index}", "-vn", "-t", "0.8",
                "-c:a", "aac", "-ac", "2", "-f", "matroska", "-y", str(output),
            ]
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=max(2, min(timeout, 60)),
                )
            except subprocess.TimeoutExpired as exc:
                raise PreflightError("Audio decoder check timed out") from exc
            except OSError as exc:
                raise PreflightError("Could not start the decoder. Check that FFmpeg is installed.") from exc
            if result.returncode != 0:
                tail = " ".join((result.stderr or "").splitlines()[-3:]).strip()
                raise PreflightError(
                    "Could not decode the audio in this file. Choose a different track or file.",
                    detail=tail[:280],
                )
            try:
                size = output.stat().st_size
            except OSError:
                size = 0
            if size <= 0:
                raise PreflightError("Audio decoder check produced no media")
            return PreflightResult(bytes_rendered=size, sample_seconds=0.8)
    if type(media.video_stream_index) is not int or media.video_stream_index < 0:
        raise PreflightError("The selected video stream index is invalid")
    tracks = media.audio_streams
    if audio_track_index >= 0:
        if not any(t.index == audio_track_index for t in tracks):
            raise PreflightError("The selected audio track is not in this movie")
        audio_map = f"0:a:{audio_track_index}"
    else:
        preferred = next((t for t in tracks if t.default), None)
        audio_map = f"0:a:{preferred.index}" if preferred else (
            f"0:a:{tracks[0].index}" if tracks else "0:a:0?"
        )
    embedded_track = next((t for t in media.subtitle_tracks
                           if embedded_subtitle_index is not None
                           and t.index == embedded_subtitle_index), None)
    if embedded_subtitle_index is not None and (
        embedded_track is None or not embedded_track.is_supported
    ):
        raise PreflightError("The selected embedded subtitle is missing or unsupported")
    with tempfile.TemporaryDirectory(prefix="smoothcast-preflight-") as folder:
        scratch = pathlib.Path(folder)
        video_filters: list[str] = []
        if subs_file is not None:
            subs_file = pathlib.Path(subs_file)
            if not subs_file.is_file():
                raise PreflightError("The selected subtitle file is missing")
            if subs_file.suffix.lower() == ".srt":
                try:
                    subs_file, _ = subtitle_encoding.stage_srt(
                        subs_file, scratch / "preflight-subs.srt",
                    )
                except subtitle_encoding.SubtitleEncodingError as exc:
                    raise PreflightError(
                        "Could not read the subtitles. Choose a valid subtitle file.",
                        detail=str(exc),
                    ) from exc
        bitmap_subtitle = bool(embedded_track and embedded_track.is_bitmap)
        if embedded_subtitle_index is not None and not bitmap_subtitle:
            video_filters.append(
                f"subtitles=filename={_filter_path(path)}:si={embedded_subtitle_index}"
            )
        elif burn_subs and subs_file is not None:
            video_filters.append(f"subtitles=filename={_filter_path(subs_file)}")
        video_filters.extend([
            "scale=w=640:h=360:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "format=yuv420p",
        ])
        output = scratch / "sample.mkv"
        args = [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(path),
        ]
        if bitmap_subtitle:
            graph = (
                f"[0:{media.video_stream_index}][0:s:{embedded_subtitle_index}]"
                "overlay=eof_action=pass:repeatlast=0,"
                + ",".join(video_filters) + "[v]"
            )
            args.extend(["-filter_complex", graph, "-map", "[v]"])
        else:
            graph = ",".join(video_filters)
            args.extend(["-map", f"0:{media.video_stream_index}", "-vf", graph])
        args.extend([
            "-map", audio_map, "-t", "0.8",
            "-r", "15", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "28", "-c:a", "aac", "-ac", "2",
            "-f", "matroska", "-y", str(output),
        ])
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=max(2, min(timeout, 60)),
            )
        except subprocess.TimeoutExpired as exc:
            raise PreflightError("MKV decoder check timed out") from exc
        except OSError as exc:
            raise PreflightError("Could not start the decoder. Check that FFmpeg is installed.") from exc
        if result.returncode != 0:
            # Retain a bounded FFmpeg tail for diagnostics.
            tail = " ".join((result.stderr or "").splitlines()[-3:]).strip()
            raise PreflightError(
                "Could not decode the video in this file. Choose a different track or file.",
                detail=tail[:280],
            )
        try:
            size = output.stat().st_size
        except OSError:
            size = 0
        if size <= 0:
            raise PreflightError("MKV decoder check produced no media")
        try:
            verify = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries", "stream=nb_read_frames",
                 "-of", "json", str(output)],
                capture_output=True, text=True, timeout=8,
            )
            streams = (json.loads(verify.stdout or "{}").get("streams") or [])
            frames = int(streams[0].get("nb_read_frames") or 0) if streams else 0
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, IndexError) as exc:
            raise PreflightError("Could not verify decoded sample video frames") from exc
        if verify.returncode != 0 or frames < 1:
            raise PreflightError("MKV decoder check produced no video frames")
        return PreflightResult(bytes_rendered=size, sample_seconds=0.8)


def fingerprint(
    media_path: pathlib.Path, *, audio_track_index: int,
    subs_file: pathlib.Path | None, burn_subs: bool,
    embedded_subtitle_index: int | None,
) -> tuple:
    """Invalidate successful preflight when media, captions or choices change."""
    path = pathlib.Path(media_path)
    info = path.stat()
    subs_fingerprint: tuple = ()
    if subs_file is not None:
        sub = pathlib.Path(subs_file)
        stat = sub.stat()
        subs_fingerprint = (str(sub), stat.st_size, stat.st_mtime_ns)
    return (
        str(path), info.st_size, info.st_mtime_ns,
        audio_track_index, subs_fingerprint, bool(burn_subs),
        embedded_subtitle_index,
    )
