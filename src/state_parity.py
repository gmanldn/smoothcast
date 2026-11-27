"""Desktop ⇄ web room state parity table (#628).

The desktop publishes its GTK-owned playback state as the room status document
built in ``cast_portal.PortalMixin._portal_handle``; ``portal_status`` publishes
it and ``GET /api/status`` serves it. This GTK-free module is the single
declaration of every desktop-visible state field: the room snapshot key it is
published under, the desktop source that produces it, its units, whether the
value is source-time or wall-clock, and what ``null`` means.

The static ratchet in ``tests/test_state_parity.py`` fails when the desktop
status document gains or loses a field without this table changing, and when the
room change-detector observes a field the desktop does not publish.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateField:
    """One desktop-visible state field and its room-snapshot mapping."""

    snapshot: str  # room snapshot key (desktop status-document key)
    desktop: str   # desktop source/attribute that produces the value
    units: str     # value shape and units
    clock: str     # "source" | "source/wall" | "none"
    null: str      # meaning of a null/empty value


FIELDS: tuple[StateField, ...] = (
    StateField("cast_feedback", "self._cast_feedback", "dict | null", "none",
               "null unless the last cast feedback belongs to the current receiver"),
    StateField("title", "self.np_title", "display text", "none",
               "empty when no media is selected"),
    StateField("receiver", "self._device()", "receiver identity string | null", "none",
               "null when no receiver is selected"),
    StateField("state", "self.device_state", "raw receiver enumeration", "none",
               "UNKNOWN when the receiver does not report a reliable state"),
    StateField("state_label", "state_labels.present(self.device_state)", "display text", "none",
               "never null; falls back to the UNKNOWN presentation"),
    StateField("state_short", "state_labels.present(self.device_state).short", "display text", "none",
               "never null; falls back to the UNKNOWN presentation"),
    StateField("state_description", "state_labels.present(self.device_state).accessible",
               "accessible description", "none",
               "never null; falls back to the UNKNOWN presentation"),
    StateField("state_icon", "state_labels.present(self.device_state).icon", "icon name", "none",
               "never null; falls back to the UNKNOWN presentation"),
    StateField("position", "self.tracker.value()", "seconds", "source",
               "null when the source position is unknown"),
    StateField("duration", "self.tracker.duration or self.media.duration", "seconds", "source",
               "0 when the source duration is unknown"),
    StateField("media_kind", "self.media.has_video / is_audio_only", "video | audio | \"\"", "none",
               "empty when the media kind is unknown"),
    StateField("rate", "self.tracker.rate", "source seconds per wall second", "source/wall",
               "clamped to 1.0 outside 0.05–4.0"),
    StateField("volume", "castctl.volume_percent(self.device_info)", "receiver percent (0–100)",
               "none", "0 when the receiver volume is unavailable"),
    StateField("queue", "self._portal_queue_status()", "ordered Up Next entry list", "none",
               "empty list when Up Next is empty"),
    StateField("queue_total", "len(self.queue)", "integer", "none",
               "full Up Next length; the queue list is capped at 100 entries"),
    StateField("queue_revision", "self._portal_observe_queue()", "monotonic integer", "none",
               "advances on any ordered Up Next change"),
    StateField("library_copies", "self._portal_copy_status()", "library copy status list", "none",
               "empty list when no library copies are tracked"),
    StateField("active", "self.session is not None or self.external", "boolean", "none",
               "never null; false when nothing owns the receiver"),
    StateField("busy", "self.busy", "boolean", "none",
               "never null; true while a command is in flight"),
    StateField("preparing", "self.busy and self._dlna_cancel is not None", "boolean", "none",
               "never null; true while a cancellable preparation runs"),
    StateField("can_stop", "action_state.can_stop(...)", "capability boolean", "none",
               "never null; false when the action is unavailable"),
    StateField("can_play_pause", "action_state.can_play_pause(...)", "capability boolean", "none",
               "never null; false when the action is unavailable"),
    StateField("can_seek", "session + tracker.known", "capability boolean", "none",
               "never null; false when the receiver cannot seek"),
    StateField("music_autogain", "self.cfg['music_autogain']", "boolean preference", "none",
               "never null; false when the preference is unset"),
    StateField("accent", "accent.normalize(self.cfg['accent'])", "accent preset id", "none",
               "never null; defaults to the built-in accent"),
    StateField("network_activity", "network_activity.portal_entries(...)", "activity entry list",
               "none", "empty list when there is no network activity"),
    StateField("session_id", "self._portal_fence.snapshot()", "fence session id | null", "none",
               "null when no command fence exists yet"),
    StateField("revision", "self._portal_fence.snapshot()", "monotonic integer | null", "none",
               "null when no command fence exists yet"),
)

BY_KEY = {field.snapshot: field for field in FIELDS}


def keys() -> frozenset[str]:
    """The room snapshot keys the desktop publishes and this table declares."""
    return frozenset(BY_KEY)
