"""Catalogue of user-visible failures with stable codes (issue #207, slice A).

GTK-free. Each entry has a plain message (what happened and the first thing to
try), ordered remediation steps and a docs anchor. Codes are stable
identifiers (``category.snake_case``) and are never translated; messages and
steps are the translatable copy. ``docs/ERRORS.md`` is generated from this
file (``python3 scripts/ci/gen_errors_doc.py``), so the two cannot drift.

Call sites are migrated in later slices; this module changes no behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

CATEGORIES = ("app", "cast", "ffmpeg", "media", "room", "upload", "internal")
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
    _spec("internal.unexpected", "error", True,
          "SmoothCast hit an unexpected problem. Retry the action.",
          "Retry the action.",
          "If it keeps happening, use Report a problem in the Help menu."),
)}

FALLBACK = CATALOGUE["internal.unexpected"]


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
