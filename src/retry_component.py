"""Retry-after-failed-cast decisions as a GTK-free component (ARCH-03, #691).

Pure rules only; ``RetryMixin`` keeps the widget/session wiring and delegates
here, so the decisions are testable without GTK and the mixin can later be
replaced by composition without changing behaviour.
"""
from __future__ import annotations

LABELS = {"retry": "Try again", "alternate_encoding": "Convert and retry"}


def action_label(kind: str, device: str) -> str:
    """Button text for the recovery plan's first option."""
    return f"Continue on {device}" if kind == "alternate_target" else LABELS.get(kind, "Try again")


def receiver_identity(name, *, cast_targets, host_for_saved, devices, saved_uuid):
    """Unique receiver identity ``(name, uuid, host)`` from cached discovery, or None.

    ``host_for_saved`` is the already-resolved host for DLNA/saved targets (or None).
    """
    if not name:
        return None
    if name.startswith("DLNA · ") or name in cast_targets:
        return (name, "", host_for_saved) if host_for_saved else None
    matches = [row for row in devices if row.name == name]
    if len(matches) != 1:
        return None
    row = matches[0]
    uuid = getattr(row, "uuid", "") or ""
    host = getattr(row, "host", "") or ""
    if (saved_uuid and uuid != saved_uuid) or not (uuid or host):
        return None
    return name, uuid, host


def playback_changed(*, closing, token, current_token, busy, external, session_active) -> bool:
    """True when something else began since the failure, so retry must not run."""
    return bool(closing or token != current_token or busy or external or session_active)


def receiver_changed(*, selection, current_selection, identity, current_identity, kind) -> bool:
    """True when the receiver differs or cannot be identified for a non-alternate retry."""
    return (current_selection != selection
            or (identity is not None and current_identity != identity)
            or (identity is None and kind != "alternate_target"))
