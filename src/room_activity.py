"""Privacy boundary for room activity: human-sized facts, never request payloads.

Room events are shared with authenticated guests. Treat every field as
untrusted regardless of which HTTP handler recorded the event. We explicitly
permit display names, known queue titles, enum actions and outcome categories;
file paths, addresses, source URLs, receiver IDs and exception text never enter
the log.
"""
from __future__ import annotations

import re

MAX_EVENT_AGE = 24 * 3600
MAX_COMMAND_KEYS = 512
MAX_ACTION = 40
OUTCOMES = frozenset({"accepted", "confirmed", "rejected", "uncertain"})
REASONS = frozenset({"permission", "conflict", "busy", "unavailable", "error"})
_ACTIONS = frozenset({
    "play_pause", "stop", "seek", "volume", "mute", "next", "previous",
    "music_autogain", "queue_play", "queue_remove", "queue_move",
    "queue_next", "queue_add_key", "queue_clear", "queue_vote",
    "play", "pause", "screen_play", "screen_pause", "screen_stop",
})
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def safe_title(value: object) -> str:
    """Accept ONLY a verified, already-shared queue display title.

    No caller-controlled event 'title' field is trusted; the room supplies
    the value from its bounded queue-title store.
    """
    if not isinstance(value, str):
        return ""
    title = "".join(ch for ch in " ".join(value.split()) if ch.isprintable())[:60]
    if (not title or title.startswith(("/", "~", "\\")) or
            bool(re.match(r"^[A-Za-z]:[\\/]", title)) or
            "://" in title or "\\" in title or "/" in title):
        return ""
    return title


def safe_name(value: object) -> str:
    if not isinstance(value, str):
        return "Someone"
    name = "".join(ch for ch in " ".join(value.split()) if ch.isprintable())[:40]
    return name or "Someone"


def event_fields(kind: str, raw: dict | None, *, actor_name: str,
                 known_title: str = "") -> dict:
    """Return a fresh, flat, tiny schema. No lists, arbitrary strings or paths."""
    data = raw if isinstance(raw, dict) else {}
    result: dict = {"name": safe_name(actor_name)}
    if kind in {"joined", "left", "renamed"}:
        if data.get("reconnected") is True:
            result["reconnected"] = True
        if data.get("expired") is True:
            result["expired"] = True
    elif kind == "voted":
        result["voted"] = data.get("voted") is True
        votes = data.get("votes")
        if type(votes) is int and 0 <= votes <= 32:
            result["votes"] = votes
    elif kind in {"action", "screen"}:
        action = data.get("action")
        if isinstance(action, str) and action in _ACTIONS:
            result["action"] = action
        else:
            result["action"] = "control"
        outcome = data.get("outcome")
        result["outcome"] = outcome if isinstance(outcome, str) and outcome in OUTCOMES else "accepted"
        reason = data.get("reason")
        if result["outcome"] in {"rejected", "uncertain"} and isinstance(reason, str) and reason in REASONS:
            result["reason"] = reason
    title = safe_title(known_title)
    if title and kind in {"action", "voted"}:
        result["title"] = title
    return result


def reason_for_status(status: int) -> str:
    """Coarse category only; never forward an exception or response string."""
    if status in (401, 403):
        return "permission"
    if status == 409:
        return "conflict"
    if status == 429:
        return "busy"
    if status == 404:
        return "unavailable"
    return "error"


def command_key(participant_id: object, command_id: object) -> tuple[str, str] | None:
    if not isinstance(participant_id, str) or not isinstance(command_id, str):
        return None
    if not _TOKEN.fullmatch(command_id) or not _TOKEN.fullmatch(participant_id):
        return None
    return participant_id, command_id
