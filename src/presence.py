"""Opt-in 'who's home' presence (#432). Pure + atomic JSON; clock injected.

A resident's phone pings ``/api/presence`` (PWA, <= every 10 min). Only ``last_seen`` is kept; there is no
history. Opting out erases it. Home = opted in and seen within ``HOME_TTL_S``. Visible to residents only.
Honest limit: a phone in a pocket with the browser closed may read as away. No scanning, Bluetooth or GPS.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

SETTING = "Count me as home when my phone is on the Wi-Fi"
MIN_PING_S, HOME_TTL_S, MAX_RESIDENTS = 600.0, 1500.0, 50
_RID = re.compile(r"[A-Za-z0-9_\-]{1,40}\Z")


class Presence:
    def __init__(self, path: Path | None = None, clock=None) -> None:
        import time
        self.path, self.clock = (Path(path) if path else None), clock or time.time
        self.d: dict[str, dict] = {}                      # rid -> {opt_in, last_seen}
        if self.path:
            try:
                raw = json.loads(self.path.read_text("utf-8"))
                for k, v in (raw.get("residents") or {}).items():
                    if _RID.match(k) and isinstance(v, dict):
                        self.d[k] = {"opt_in": v.get("opt_in") is True, "last_seen": v.get("last_seen") if isinstance(v.get("last_seen"), (int, float)) else None}
            except (OSError, ValueError, AttributeError):
                pass

    def set_opt_in(self, rid: str, on: bool) -> bool:
        if not isinstance(rid, str) or not _RID.match(rid) or (rid not in self.d and len(self.d) >= MAX_RESIDENTS):
            return False
        self.d[rid] = {"opt_in": bool(on), "last_seen": None}      # toggling either way drops any old sighting
        self._save()
        return True

    def ping(self, rid: str) -> dict:
        e = self.d.get(rid)
        if not e or not e["opt_in"]:
            return {"ok": False, "error": "Presence is off for this person."}
        now = self.clock()
        if e["last_seen"] is not None and now - e["last_seen"] < MIN_PING_S / 2:
            return {"ok": True, "throttled": True}
        e["last_seen"] = now
        self._save()
        return {"ok": True, "next_ping_s": MIN_PING_S}

    def home(self, rid: str) -> bool:
        e = self.d.get(rid)
        return bool(e and e["opt_in"] and e["last_seen"] is not None and 0 <= self.clock() - e["last_seen"] < HOME_TTL_S)

    def listing(self, viewer_rid: str | None, residents: list[str]) -> list[dict] | None:
        """GET /api/presence -> [{resident_id, home}] for opted-in residents; None (403) for non-residents."""
        if viewer_rid is None or viewer_rid not in residents:
            return None
        return [{"resident_id": r, "home": self.home(r)} for r in residents if self.d.get(r, {}).get("opt_in")]

    def at_home(self, residents: list[str]) -> list[str]:
        """Small interface for suggestions / the movie picker (#392)."""
        return [r for r in residents if self.home(r)]

    def forget(self, rid: str) -> None:
        if self.d.pop(rid, None) is not None:
            self._save()

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".pr")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "residents": self.d}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
