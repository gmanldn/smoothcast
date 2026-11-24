"""Pure recovery plan after a failed cast launch, seek or transfer (#13, SC-006).

Given what failed and what was already tried, answer: where does playback
resume, and which one-click options does the user get, each with a plain
reason. GTK-free, no I/O, no receiver commands and no state: the caller keeps
the local position and renders the options. Every option is a *suggestion*; a
caller must still run its normal preflight and ownership checks before acting.

Options come in a fixed order: retry, a different encoding, a different target.
A (target, mode) pair that has already failed twice is never offered again, so
a UI built on this cannot loop a user through the same broken combination.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

from errors import CATALOGUE, FALLBACK, ErrorSpec

Kind = Literal["retry", "alternate_encoding", "alternate_target"]
Stage = Literal["launch", "seek", "transfer"]

# Cheapest -> most compatible. A receiver that cannot take the file as-is may
# take a remux, and failing that a full transcode.
ENCODING_LADDER = ("direct", "remux", "transcode")
MAX_ATTEMPTS = 2  # per (target, mode) pair
MAX_TARGET_OPTIONS = 3
MAX_NAME = 64
_ALL: frozenset[Kind] = frozenset({"retry", "alternate_encoding", "alternate_target"})
# What can plausibly help for a given catalogued failure. Anything absent (or an
# uncatalogued failure) may be a transient or encoding problem: offer everything.
_HELPS: dict[str, frozenset[Kind]] = {
    "cast.receiver_offline": frozenset({"retry", "alternate_target"}),
    "cast.command_in_progress": frozenset({"retry"}),
    "cast.playback_changed": frozenset({"retry"}),
    "cast.no_supported_format": frozenset({"alternate_target"}),
    "cast.settings_unsupported": frozenset({"alternate_target"}),
    "cast.audio_only_unverified": frozenset({"alternate_target"}),
    "ffmpeg.decoder_timeout": frozenset({"retry", "alternate_encoding"}),
    "ffmpeg.decoder_failed": frozenset(),  # a media problem, not a receiver one
    "media.unavailable": frozenset(),
    "media.changed": frozenset({"retry"}),
}
_KEYWORDS = (
    ("cast.receiver_offline", ("offline", "unreachable", "not reachable", "connection refused",
                               "no route", "timed out connecting")),
    ("cast.no_supported_format", ("no supported format", "unsupported format", "unsupported media",
                                  "codec not supported")),
    ("ffmpeg.decoder_timeout", ("probe timed out", "took too long")),
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f‪-‮⁦-⁩]")


@dataclass(frozen=True)
class FailureContext:
    """Facts the caller already holds. ``position`` is the last *confirmed* second."""
    device: str
    mode: str = "direct"
    stage: Stage = "launch"
    error_code: str | None = None
    position: float | None = None
    duration: float | None = None
    targets: tuple[str, ...] = ()  # other receivers currently discovered
    tried: tuple[tuple[str, str], ...] = ()  # pairs that failed BEFORE this failure


@dataclass(frozen=True)
class RecoveryOption:
    kind: Kind
    label: str
    reason: str
    device: str
    mode: str
    position: float


@dataclass(frozen=True)
class RecoveryPlan:
    position: float
    headline: str
    steps: tuple[str, ...]
    options: tuple[RecoveryOption, ...]

    @property
    def primary(self) -> RecoveryOption | None:
        """The single one-click suggestion, or None when nothing can help."""
        return self.options[0] if self.options else None


def classify_message(message: str | None) -> str | None:
    """Best-effort catalogue code from legacy free-text; None when unsure."""
    text = (message or "").lower()
    for code, needles in _KEYWORDS:
        if any(needle in text for needle in needles):
            return code
    return None


def safe_position(position: float | None, duration: float | None = None) -> float:
    """Resume point: finite, non-negative, never past the end."""
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        return 0.0
    value = float(position)
    if not math.isfinite(value) or value < 0:
        return 0.0
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) \
            and math.isfinite(duration) and duration > 0:
        value = min(value, float(duration))
    return value


def format_position(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _clean(name: object) -> str:
    return _CONTROL.sub("", name).strip()[:MAX_NAME] if isinstance(name, str) else ""


def _spec(code: str | None) -> ErrorSpec:
    return CATALOGUE.get(code or "", FALLBACK)


def plan_recovery(ctx: FailureContext) -> RecoveryPlan:
    """Resume point plus ordered, de-duplicated recovery options."""
    spec = _spec(ctx.error_code)
    allowed = _HELPS.get(spec.code, _ALL) if spec is not FALLBACK else _ALL
    position = safe_position(ctx.position, ctx.duration)
    device, mode = _clean(ctx.device), ctx.mode
    failures: dict[tuple[str, str], int] = {}
    for pair in ctx.tried[:64]:
        failures[pair] = failures.get(pair, 0) + 1
    failures[(device, mode)] = failures.get((device, mode), 0) + 1  # ``tried`` excludes this failure
    options: list[RecoveryOption] = []
    where = "while seeking" if ctx.stage == "seek" else "while starting" if ctx.stage == "launch" \
        else "during playback"

    if "retry" in allowed and spec.retryable and failures[(device, mode)] < MAX_ATTEMPTS:
        options.append(RecoveryOption(
            "retry", f"Try again on {device}", spec.message, device, mode, position))
    if "alternate_encoding" in allowed and mode in ENCODING_LADDER:
        for later in ENCODING_LADDER[ENCODING_LADDER.index(mode) + 1:]:
            if failures.get((device, later), 0) < MAX_ATTEMPTS:
                options.append(RecoveryOption(
                    "alternate_encoding", f"Convert for {device} ({later})",
                    f"{device} could not play this {where}; converting it to a more "
                    "widely supported format may help.", device, later, position))
                break
    if "alternate_target" in allowed:
        seen: set[str] = {device}
        for raw in ctx.targets[:32]:
            name = _clean(raw)
            if not name or name in seen:
                continue
            seen.add(name)
            if failures.get((name, mode), 0) >= MAX_ATTEMPTS:
                continue
            options.append(RecoveryOption(
                "alternate_target", f"Continue on {name}",
                f"Casting to {device} failed {where}; {name} is available now.",
                name, mode, position))
            if sum(o.kind == "alternate_target" for o in options) >= MAX_TARGET_OPTIONS:
                break
    headline = f"{spec.message} Your place ({format_position(position)}) is saved."
    return RecoveryPlan(position, headline, spec.steps, tuple(options))


def plan_for_window(window: object, message: str | None = None) -> RecoveryPlan | None:
    """Recovery plan from a live main window; None on ANY problem.

    Reads only (device, tracker position, session mode, discovered names) and
    never raises, so calling it from failure handling cannot make a failure
    worse. Call it before the tracker is cleared.
    """
    try:
        device = str(window._device() or "")  # type: ignore[attr-defined]
        if not device:
            return None
        tracker = getattr(window, "tracker", None)
        position = tracker.value() if tracker is not None else None
        session = getattr(window, "session", None)
        mode = str(getattr(window, "_attempt_mode", "") or getattr(session, "mode", "") or "direct")
        tried = tuple((str(d), str(m)) for d, m in list(getattr(window, "_cast_tried", ()) or ())[-16:])
        names = tuple(str(getattr(d, "name", "")) for d in (getattr(window, "devices", None) or ())[:64])
        info = getattr(window, "device_info", None)
        duration = info.get("duration") if isinstance(info, dict) else None
        return plan_recovery(FailureContext(
            device=device, mode=mode, stage="launch" if session is None else "transfer",
            error_code=classify_message(message), position=position, duration=duration,
            targets=tuple(n for n in names if n), tried=tried))
    except Exception:  # noqa: BLE001 - observation must never break failure handling
        return None


def summary_line(plan: RecoveryPlan) -> str:
    """One console line: saved position and the option kinds, no receiver names."""
    kinds = ", ".join(dict.fromkeys(o.kind for o in plan.options)) or "none"
    return f"Recovery: place {format_position(plan.position)} saved; options: {kinds}"
