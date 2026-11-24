"""Catalogue of user-visible failures with stable codes (issue #207, slice A).

GTK-free. Each entry has a plain message (what happened and the first thing to
try), ordered remediation steps and a docs anchor. Codes are stable
identifiers (``category.snake_case``) and are never translated; messages and
steps are the translatable copy. ``docs/ERRORS.md`` is generated from this
file (``python3 scripts/ci/gen_errors_doc.py``), so the two cannot drift.

Call sites are migrated in later slices; this module changes no behaviour.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time

CATEGORIES = ("app", "cast", "ffmpeg", "media", "room", "subtitle", "upload", "internal")
SEVERITIES = ("info", "warning", "error")


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    category: str
    severity: str
    retryable: bool
    message: str
    steps: tuple[str, ...]

    @property
    def docs_anchor(self) -> str:
        return "errors-" + self.code.replace(".", "-").replace("_", "-")


def _spec(code: str, severity: str, retryable: bool, message: str, *steps: str) -> ErrorSpec:
    return ErrorSpec(code, code.split(".", 1)[0], severity, retryable, message, tuple(steps))


CATALOGUE: dict[str, ErrorSpec] = {s.code: s for s in (
    _spec("cast.receiver_offline", "error", True,
          "Receiver offline. Check its power and network connection.",
          "Check that the receiver is switched on.",
          "Check that it is on the same network as this computer.",
          "Choose the receiver again from the list."),
    _spec("cast.command_in_progress", "info", True,
          "SmoothCast is finishing another command. Wait a moment, then retry.",
          "Wait a few seconds.", "Retry the action."),
    _spec("cast.playback_changed", "info", True,
          "Playback changed. Refresh the room before retrying.",
          "Refresh the room.", "Retry the action if it still applies."),
    _spec("ffmpeg.too_old", "error", False,
          "FFmpeg is too old or missing. SmoothCast needs FFmpeg 5.0 or newer.",
          "Install FFmpeg 5.0 or newer.", "Restart SmoothCast."),
    _spec("media.unavailable", "warning", False,
          "That media is no longer available. Choose it again.",
          "Check that the file still exists and its drive is connected.",
          "Add it to Up Next again."),
    _spec("room.session_expired", "info", True,
          "Your room session ended. Join the room again.",
          "Reload the page.", "Enter your name to rejoin."),
    _spec("room.queue_item_gone", "info", True,
          "That Up Next item is no longer there. Refresh the room.",
          "Refresh the room to see the current Up Next."),
    _spec("room.rate_limited", "info", True,
          "Too many commands in a short time. Try again shortly.",
          "Wait a few seconds.", "Retry the action."),
    _spec("upload.not_found", "warning", True,
          "Upload not found. Choose the file again.",
          "Choose the file again to restart the upload."),
    _spec("upload.disk_full", "error", False,
          "Not enough free space to receive this file. Free some space, then retry.",
          "Free disk space on the computer running SmoothCast.", "Retry the upload."),
    _spec("app.shutting_down", "info", False,
          "SmoothCast is shutting down. Reconnect when it has restarted.",
          "Wait for SmoothCast to start again.", "Reload the page."),
    _spec("ffmpeg.missing", "error", False,
          "FFmpeg is missing or cannot start. SmoothCast needs FFmpeg 5.0 or newer.",
          "Install FFmpeg 5.0 or newer.", "Restart SmoothCast."),
    _spec("ffmpeg.decoder_failed", "error", False,
          "SmoothCast could not decode this file. Choose a different track or file.",
          "Choose another audio track or subtitle option.", "Try a different file."),
    _spec("ffmpeg.decoder_timeout", "warning", True,
          "Checking this file took too long. Try again or choose a different file.",
          "Retry the action.", "Try a different file if it keeps happening."),
    _spec("ffmpeg.probe_missing", "error", False,
          "ffprobe is missing. Install FFmpeg, which includes it.",
          "Install FFmpeg 5.0 or newer.", "Restart SmoothCast."),
    _spec("media.probe_failed", "warning", True,
          "SmoothCast could not read this file. Check that it is a playable media file.",
          "Check that the file opens in another player.", "Choose a different file."),
    _spec("media.audio_track_missing", "warning", False,
          "The selected audio track is not in this file. Choose Auto or another track.",
          "Set the audio track to Auto.", "Choose another track."),
    _spec("media.no_audio_stream", "warning", False,
          "This file has no audio. Choose a different file.",
          "Choose a different file."),
    _spec("media.changed", "info", True,
          "The queued item changed. Try casting it again.",
          "Cast it again."),
    _spec("subtitle.unavailable", "warning", False,
          "The selected subtitles are unavailable. Choose other subtitles or turn them off.",
          "Choose another subtitle track.", "Turn subtitles off."),
    _spec("subtitle.unreadable", "warning", False,
          "SmoothCast could not read these subtitles. Choose a valid subtitle file.",
          "Choose a different subtitle file.", "Turn subtitles off."),
    _spec("subtitle.audio_only", "info", False,
          "Audio-only media does not support subtitles. Choose Auto or Off.",
          "Set subtitles to Off."),
    _spec("cast.no_supported_format", "error", False,
          "This receiver advertises no format SmoothCast can send. Choose another receiver.",
          "Choose another receiver.", "Try a Google Cast target."),
    _spec("cast.settings_unsupported", "warning", False,
          "This receiver needs normal speed and unrotated video. Reset those settings and retry.",
          "Reset speed to normal.", "Turn rotation off.", "Retry the action."),
    _spec("cast.audio_only_unverified", "warning", False,
          "This DLNA receiver is not verified for audio-only playback. Choose a Google Cast target.",
          "Choose a Google Cast target."),
    _spec("internal.unexpected", "error", True,
          "SmoothCast hit an unexpected problem. Retry the action.",
          "Retry the action.",
          "If it keeps happening, use Report a problem in the Help menu."),
)}

FALLBACK = CATALOGUE["internal.unexpected"]

_RECENT: "deque[tuple[float, str, dict[str, str]]]" = deque(maxlen=20)
_RECENT_LOCK = threading.Lock()
_MAX_CONTEXT_KEYS = 6
_MAX_CONTEXT_VALUE = 120


def _bounded_context(context: object) -> dict[str, str]:
    """Clip structured context to a few short string facts (callers pre-redact)."""
    if not isinstance(context, dict):
        return {}
    clean: dict[str, str] = {}
    for key, value in context.items():
        if len(clean) >= _MAX_CONTEXT_KEYS:
            break
        if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
            clean[key[:40]] = str(value)[:_MAX_CONTEXT_VALUE]
    return clean


def record(code: str, context: object = None) -> None:
    """Remember that ``code`` reached a user (bounded ring; context is clipped)."""
    entry = (time.time(), code if code in CATALOGUE else FALLBACK.code, _bounded_context(context))
    with _RECENT_LOCK:
        _RECENT.append(entry)


def recent() -> list[dict]:
    """Last error codes shown, oldest first, for the diagnostics bundle.

    A snapshot taken under the lock; context dicts are copied so a caller can
    neither race a concurrent ``record`` nor edit the stored history.
    """
    with _RECENT_LOCK:
        snapshot = list(_RECENT)
    return [{"at": int(at), "code": code, **({"context": dict(ctx)} if ctx else {})}
            for at, code, ctx in snapshot]


def reset_recent() -> None:
    with _RECENT_LOCK:
        _RECENT.clear()


class SmoothCastError(Exception):
    """An error with a catalogued code; ``context`` holds already-redacted facts."""

    def __init__(self, code: str, *, context: dict[str, str] | None = None,
                 detail: str = "") -> None:
        self.spec = CATALOGUE.get(code, FALLBACK)
        self.context = dict(context or {})
        super().__init__(f"{self.spec.code}: {detail}" if detail else self.spec.code)

    @property
    def user_message(self) -> str:  # honoured by failure_boundary.describe
        return self.spec.message

    @property
    def steps(self) -> tuple[str, ...]:
        return self.spec.steps


def describe(exc: object) -> ErrorSpec:
    """Catalogue entry for ``exc``; anything uncatalogued is ``internal.unexpected``."""
    spec = getattr(exc, "spec", None)
    return spec if isinstance(spec, ErrorSpec) else FALLBACK
