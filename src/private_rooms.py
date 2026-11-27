"""Private rooms (#376). Pure visibility and control policy over the rooms store.

A room with ``private_to`` is visible/controllable only by those residents, plus the host.
The host can always see and stop (``host_stop``) but each use is logged. An owner may share
the room with others until ``share_until``. A deleted owner makes the room public again and
the host is told. Filtering applies to pickers, status, activity and API payloads alike.
"""
from __future__ import annotations

SHARE_MAX_S = 24 * 3600


def can_see(room: dict, actor: str | None, role: str, now: float) -> bool:
    owners = room.get("private_to") or []
    if not owners or role == "host":
        return True
    if actor in owners:
        return True
    until = room.get("share_until")
    return isinstance(until, (int, float)) and now < until


def can_control(room: dict, actor: str | None, role: str, now: float) -> bool:
    """Same as visibility for now: anyone who can see a shared room can use it; the host always can."""
    return can_see(room, actor, role, now)


def visible_rooms(rooms: list[dict], actor: str | None, role: str, now: float) -> list[dict]:
    return [r for r in rooms if can_see(r, actor, role, now)]


def hidden_receivers(rooms: list[dict], actor: str | None, role: str, now: float) -> set[str]:
    return {x for r in rooms if not can_see(r, actor, role, now) for x in r.get("receivers", [])}


def filter_receivers(items: list[dict], rooms: list[dict], actor: str | None, role: str, now: float, key: str = "id") -> list[dict]:
    """Strip hidden receivers from any list (pickers, status, network activity, API rows)."""
    hide = hidden_receivers(rooms, actor, role, now)
    return [i for i in items if i.get(key) not in hide]


def set_private(room: dict, owners: list[str], actor: str, role: str) -> tuple[bool, str]:
    if role != "host" and actor not in (room.get("private_to") or []):
        return False, "Only the host or the room's owner can change this."
    room["private_to"] = sorted({o for o in owners if o})
    if not room["private_to"]:
        room.pop("share_until", None)
    return True, ""


def share(room: dict, actor: str, seconds: float, now: float) -> tuple[bool, str]:
    if actor not in (room.get("private_to") or []):
        return False, "Only the owner can share this room."
    room["share_until"] = now + max(0.0, min(float(seconds), SHARE_MAX_S))
    return True, ""


def unshare(room: dict, actor: str) -> bool:
    if actor not in (room.get("private_to") or []):
        return False
    room.pop("share_until", None)
    return True


def host_stop(room: dict, actor: str, now: float, log: list) -> bool:
    """The host can always stop a private room (forgotten alarm). Logged, never silent."""
    if not room.get("private_to"):
        return True
    log.append({"at": now, "actor": actor, "room": room.get("id"), "action": "host_stop_private"})
    return True


def owner_deleted(rooms: list[dict], resident_id: str) -> list[str]:
    """Remove a deleted resident from private_to; rooms left ownerless become public. Returns host notices."""
    notices = []
    for r in rooms:
        owners = r.get("private_to") or []
        if resident_id in owners:
            r["private_to"] = [o for o in owners if o != resident_id]
            if not r["private_to"]:
                r.pop("share_until", None)
                notices.append(f"{r.get('name', 'A room')} is no longer private because its owner was removed.")
    return notices


def lock_tooltip(room: dict, actor: str | None) -> str | None:
    owners = room.get("private_to") or []
    if not owners:
        return None
    return "Only you can see this room" if actor in owners else "Private room"


def api_status(room: dict | None, actor: str | None, role: str, now: float) -> int:
    """Direct room/receiver API: 404 (not 403) for non-owners so existence isn't leaked."""
    return 200 if room is not None and can_see(room, actor, role, now) else 404
