"""Host-side participant panel model and room policy store (#322). Pure + atomic file IO.

``rows`` turns raw participant records into display rows (friendly name, role,
activity age, connection). ``Policy`` holds only non-secret room settings
(default guest role, lock) and saves them atomically; session tokens are never
stored, so restart keeps policy but drops old guest sessions.
"""
from __future__ import annotations

import json
from pathlib import Path

ROLES = ("viewer", "controller", "host")
ONLINE_S = 30.0


def age_label(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 10:
        return "just now"
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    return f"{s // 3600} h ago"


def rows(participants: list[dict], now: float) -> list[dict]:
    out = []
    for p in participants or []:
        seen = p.get("last_seen")
        age = (now - seen) if isinstance(seen, (int, float)) else None
        role = p.get("role") if p.get("role") in ROLES else "viewer"
        out.append({
            "id": str(p.get("id", "")),
            "name": (str(p.get("name") or "").strip() or "Guest")[:40],
            "role": role,
            "activity": age_label(age) if age is not None else "never",
            "online": age is not None and age <= ONLINE_S,
            "can_change": role != "host",       # the host row is never demotable/revocable
        })
    out.sort(key=lambda r: (not r["online"], r["name"].lower()))
    return out


def empty_message(participants: list[dict]) -> str:
    return "" if participants else "Nobody has joined yet. Share the room link or PIN from the front page."


class Policy:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.default_role = "viewer"
        self.locked = False
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if data.get("default_role") in ROLES[:2]:
                self.default_role = data["default_role"]
            self.locked = data.get("locked") is True
        except (OSError, ValueError, AttributeError):
            pass

    def set_default_role(self, role: str) -> bool:
        if role not in ROLES[:2]:           # a new guest can never default to host
            return False
        self.default_role = role
        self._save()
        return True

    def set_locked(self, locked: bool) -> None:
        self.locked = bool(locked)
        self._save()

    def role_for_new_guest(self) -> str | None:
        return None if self.locked else self.default_role

    def _save(self) -> None:
        import store  # atomic, fsynced, owner-only (#701)
        if not store.Store(self.path).write({"default_role": self.default_role, "locked": self.locked}):
            raise OSError(f"could not save {self.path}")
