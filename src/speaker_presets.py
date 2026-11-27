"""Speaker group presets (#371). Pure planning; the caller applies the plan.

A preset is {id, name, entries:[{room, volume: 0-100|None}], edited, updated_at}. ``plan_recall``
returns which rooms to group, the volumes to set (clamped by #330 ceilings), rooms skipped
because their receiver is offline, and the toast. Current playback is never touched.
"""
from __future__ import annotations

import secrets

MAX_PRESETS = 20


def save(presets: list[dict], name: str, entries: list[dict], now: float, preset_id: str | None = None) -> tuple[list[dict], str | None]:
    name = (name or "").strip()[:30]
    clean = []
    for e in entries:
        v = e.get("volume")
        clean.append({"room": str(e["room"]), "volume": None if v is None else max(0, min(100, int(v)))})
    if not name or not clean:
        return presets, None
    others = [p for p in presets if p["id"] != preset_id]
    if any(p["name"].lower() == name.lower() for p in others):
        return presets, None
    if preset_id is None and len(presets) >= MAX_PRESETS:
        return presets, None
    pid = preset_id or "pre" + secrets.token_hex(4)
    new = {"id": pid, "name": name, "entries": clean, "edited": False, "updated_at": now}
    return others + [new], pid


def prune(presets: list[dict], live_rooms: set[str]) -> list[dict]:
    """Drop entries for deleted rooms; mark the preset edited; drop presets left empty."""
    out = []
    for p in presets:
        keep = [e for e in p["entries"] if e["room"] in live_rooms]
        if not keep:
            continue
        out.append({**p, "entries": keep, "edited": p.get("edited", False) or len(keep) != len(p["entries"])})
    return out


def plan_recall(preset: dict, rooms: dict[str, dict], online: dict[str, bool], ceilings: dict[str, float] | None = None,
                guest: bool = False, guests_allowed: bool = False) -> dict:
    """rooms: id -> {name, receiver}. online: receiver -> bool. ceilings: receiver -> 0..1."""
    if guest and not guests_allowed:
        return {"ok": False, "reason": "Presets are turned off for guests.", "group": [], "volumes": {}, "skipped": [], "toast": ""}
    group, volumes, skipped = [], {}, []
    for e in preset["entries"]:
        room = rooms.get(e["room"])
        if room is None:
            continue
        rx = room.get("receiver")
        if not rx or not online.get(rx):
            skipped.append(room["name"])
            continue
        group.append(rx)
        if e["volume"] is not None:
            v = e["volume"] / 100
            cap = (ceilings or {}).get(rx)
            volumes[rx] = min(v, cap) if cap is not None else v
    if not group:
        return {"ok": False, "reason": "None of those rooms are available right now.", "group": [], "volumes": {}, "skipped": skipped, "toast": ""}
    toast = f"{preset['name']} on" + "".join(f" · {n} skipped (speaker offline)" for n in skipped)
    return {"ok": True, "reason": "", "group": group, "volumes": volumes, "skipped": skipped, "toast": toast}
