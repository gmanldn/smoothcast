"""Named rooms for receivers (#370). Pure, newest-wins merge with tombstones, atomic JSON.

``rooms.json``: {version:1, rooms:[{id,name,icon,receivers,default_video,default_audio,updated_at}],
tombstones:{room_id: deleted_at}}. A receiver lives in at most one room.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path

VERSION = 1
ICONS = ("tv", "sofa", "bed", "kitchen", "garden", "office")
MAX_ROOMS, MAX_NAME = 30, 30


class Rooms:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.rooms: dict[str, dict] = {}
        self.tombstones: dict[str, float] = {}
        if self.path:
            try:
                d = json.loads(self.path.read_text("utf-8"))
                if d.get("version") == VERSION:
                    self.rooms = {r["id"]: r for r in d.get("rooms", []) if isinstance(r, dict) and "id" in r}
                    self.tombstones = {k: float(v) for k, v in d.get("tombstones", {}).items()}
            except (OSError, ValueError, AttributeError, KeyError, TypeError):
                pass

    # -- editing -------------------------------------------------------
    def add(self, name: str, icon: str, now: float) -> str | None:
        name = (name or "").strip()[:MAX_NAME]
        if not name or len(self.rooms) >= MAX_ROOMS or any(r["name"].lower() == name.lower() for r in self.rooms.values()):
            return None
        rid = "room" + secrets.token_hex(4)
        self.rooms[rid] = {"id": rid, "name": name, "icon": icon if icon in ICONS else "tv", "receivers": [],
                           "default_video": None, "default_audio": None, "updated_at": now}
        self._save()
        return rid

    def _touch(self, rid: str, now: float) -> None:
        self.rooms[rid]["updated_at"] = now
        self._save()

    def rename(self, rid: str, name: str, now: float) -> bool:
        name = (name or "").strip()[:MAX_NAME]
        if rid not in self.rooms or not name or any(k != rid and r["name"].lower() == name.lower() for k, r in self.rooms.items()):
            return False
        self.rooms[rid]["name"] = name
        self._touch(rid, now)
        return True

    def assign(self, rid: str, receiver: str, now: float) -> bool:
        if rid not in self.rooms or not receiver:
            return False
        for k, r in self.rooms.items():                       # one room per receiver
            if receiver in r["receivers"] and k != rid:
                r["receivers"].remove(receiver)
                for d in ("default_video", "default_audio"):
                    if r[d] == receiver:
                        r[d] = None
                self._touch(k, now)
        if receiver not in self.rooms[rid]["receivers"]:
            self.rooms[rid]["receivers"].append(receiver)
        self._touch(rid, now)
        return True

    def set_default(self, rid: str, kind: str, receiver: str | None, now: float) -> bool:
        if rid not in self.rooms or kind not in ("video", "audio") or (receiver and receiver not in self.rooms[rid]["receivers"]):
            return False
        self.rooms[rid][f"default_{kind}"] = receiver
        self._touch(rid, now)
        return True

    def delete(self, rid: str, now: float) -> bool:
        if self.rooms.pop(rid, None) is None:
            return False
        self.tombstones[rid] = now
        self._save()
        return True

    # -- sync ----------------------------------------------------------
    def state(self) -> dict:
        return {"version": VERSION, "rooms": list(self.rooms.values()), "tombstones": dict(self.tombstones)}

    def merge(self, peer: dict) -> int:
        """Newest-wins per room; a delete beats an older edit, a newer edit beats an older delete."""
        changed = 0
        try:
            for rid, t in (peer.get("tombstones") or {}).items():
                t = float(t)
                cur = self.rooms.get(rid)
                if t > self.tombstones.get(rid, -1):
                    self.tombstones[rid] = t
                if cur and t >= cur["updated_at"]:
                    del self.rooms[rid]
                    changed += 1
            for r in peer.get("rooms") or []:
                rid, ts = r["id"], float(r["updated_at"])
                if ts <= self.tombstones.get(rid, -1):
                    continue
                cur = self.rooms.get(rid)
                if cur is None or ts > cur["updated_at"]:
                    self.rooms[rid] = {**r, "receivers": list(r.get("receivers") or [])}
                    changed += 1
        except (KeyError, TypeError, ValueError, AttributeError):
            return changed
        if changed:
            self._dedupe_receivers()
            self._save()
        return changed

    def _dedupe_receivers(self) -> None:
        seen: dict[str, str] = {}
        for rid, r in sorted(self.rooms.items(), key=lambda kv: -kv[1]["updated_at"]):
            r["receivers"] = [x for x in r["receivers"] if seen.setdefault(x, rid) == rid]

    # -- views ---------------------------------------------------------
    def picker(self, receivers: list[dict]) -> dict:
        """receivers: {id,name,online}. Rooms first with subtitle, then 'Other devices'."""
        by_id = {r["id"]: r for r in receivers}
        rows, claimed = [], set()
        for room in sorted(self.rooms.values(), key=lambda r: r["name"].lower()):
            devs = [by_id[x] for x in room["receivers"] if x in by_id]
            claimed.update(room["receivers"])
            online = any(d["online"] for d in devs)
            names = " + ".join(d["name"] for d in devs) or "No devices"
            rows.append({"id": room["id"], "name": room["name"], "icon": room["icon"],
                         "subtitle": f"{names} · {'on' if online else 'offline'}" if devs else names, "online": online,
                         "video": room["default_video"], "audio": room["default_audio"]})
        other = [d for d in receivers if d["id"] not in claimed]
        return {"rooms": rows, "other": other}

    def unassigned(self, receivers: list[dict], dismissed: set[str]) -> list[dict]:
        claimed = {x for r in self.rooms.values() for x in r["receivers"]}
        return [d for d in receivers if d["id"] not in claimed and d["id"] not in dismissed]

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".rooms")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.state(), fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
