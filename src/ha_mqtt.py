"""Home Assistant MQTT bridge policy (#383). Pure: topics, discovery payloads, state, commands, backoff.

No broker I/O. A thin client feeds ``state_messages`` / ``handle_command`` and applies ``Backoff``.
Read-only by default: commands are ignored unless the host enabled control. Private rooms are never
announced; titles are omitted when the privacy mode hides them. Last-will marks everything unavailable.
"""
from __future__ import annotations

import json
import re

PREFIX, DISCOVERY = "smoothcast", "homeassistant"
STATES = {"playing": "playing", "paused": "paused", "buffering": "buffering", "idle": "idle", "stopped": "idle", "off": "off"}
COMMANDS = {"play", "pause", "stop", "next", "previous", "volume_set", "select_source", "move_to"}
ALWAYS_SAFE = set()                                      # nothing is allowed while read-only
FEATURES = ("PLAY", "PAUSE", "STOP", "NEXT_TRACK", "PREVIOUS_TRACK", "VOLUME_SET", "SELECT_SOURCE")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40] or "room"


def topics(node: str, room: str) -> dict:
    base = f"{PREFIX}/{slug(node)}/{slug(room)}"
    return {"state": f"{base}/state", "attrs": f"{base}/attributes", "avail": f"{PREFIX}/{slug(node)}/status",
            "cmd": f"{base}/set", "config": f"{DISCOVERY}/media_player/{slug(node)}_{slug(room)}/config"}


def publishable(room: dict) -> bool:
    return not room.get("private")


def discovery(node: str, room: dict, sources: list[str], control: bool, version: str = "") -> tuple[str, str] | None:
    """(topic, json) for HA MQTT discovery, or None for private rooms."""
    if not publishable(room):
        return None
    t = topics(node, room["name"])
    cfg = {"name": room["name"][:40], "unique_id": f"{slug(node)}_{slug(room['name'])}", "object_id": f"smoothcast_{slug(room['name'])}",
           "state_topic": t["state"], "json_attributes_topic": t["attrs"], "availability_topic": t["avail"],
           "payload_available": "online", "payload_not_available": "offline",
           "device": {"identifiers": [f"smoothcast_{slug(node)}"], "name": f"SmoothCast {node}"[:50], "manufacturer": "SmoothCast", "sw_version": version or None}}
    if not cfg["device"]["sw_version"]:
        del cfg["device"]["sw_version"]
    if control:
        cfg["command_topic"] = t["cmd"]
        cfg["supported_features"] = list(FEATURES)
        cfg["source_list"] = sorted(set(sources))[:50]
    return t["config"], json.dumps(cfg, sort_keys=True)


def state_messages(node: str, room: dict, privacy_hides_titles: bool = False) -> list[tuple[str, str, bool]]:
    """[(topic, payload, retain)]. Private rooms publish nothing."""
    if not publishable(room):
        return []
    t = topics(node, room["name"])
    st = STATES.get(room.get("state", "idle"), "idle")
    attrs = {"volume_level": round(max(0, min(100, room.get("volume", 0))) / 100, 2), "source": room.get("source")}
    if st in ("playing", "paused", "buffering"):
        attrs["media_position"], attrs["media_duration"] = room.get("position"), room.get("duration")
        if not privacy_hides_titles and not room.get("hide_title"):
            attrs["media_title"] = (room.get("title") or "")[:120]
    attrs = {k: v for k, v in attrs.items() if v is not None}
    return [(t["state"], st, True), (t["attrs"], json.dumps(attrs, sort_keys=True), True)]


def availability(node: str, online: bool) -> tuple[str, str, bool]:
    return topics(node, "x")["avail"], "online" if online else "offline", True


def last_will(node: str) -> dict:
    return {"topic": topics(node, "x")["avail"], "payload": "offline", "retain": True, "qos": 1}


def handle_command(topic: str, payload: str, node: str, rooms: list[dict], control: bool) -> dict:
    """-> {ok, room, action, arg} or {ok False, reason}. Read-only mode ignores everything."""
    if not control:
        return {"ok": False, "reason": "read_only"}
    for r in rooms:
        if publishable(r) and topics(node, r["name"])["cmd"] == topic:
            break
    else:
        return {"ok": False, "reason": "unknown_room"}
    try:
        d = json.loads(payload)
        action, arg = (d.get("command"), d.get("value")) if isinstance(d, dict) else (None, None)
    except ValueError:
        action, arg = (payload or "").strip().lower(), None
    if action not in COMMANDS:
        return {"ok": False, "reason": "unknown_command"}
    if action == "volume_set":
        try:
            arg = max(0, min(100, int(round(float(arg) * (100 if isinstance(arg, float) and arg <= 1 else 1)))))
        except (TypeError, ValueError):
            return {"ok": False, "reason": "bad_value"}
    elif action in ("select_source", "move_to"):
        if not isinstance(arg, str) or not any(publishable(x) and x["name"] == arg for x in rooms) and action == "move_to":
            return {"ok": False, "reason": "bad_value"}
    return {"ok": True, "room": r["name"], "action": action, "arg": arg}


class Backoff:
    """Reconnect delay: 1 s doubling to 60 s with deterministic jitter-free steps; reset on success."""

    def __init__(self, base: float = 1.0, cap: float = 60.0) -> None:
        self.base, self.cap, self.n = base, cap, 0

    def next(self) -> float:
        d = min(self.cap, self.base * 2 ** self.n)
        self.n += 1
        return d

    def reset(self) -> None:
        self.n = 0
