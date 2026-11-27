"""Resident (household member) profile store (#363). Schema version 1, atomic JSON.

PINs (4-8 digits, separate from the room PIN) are kept only as salted scrypt
hashes. ``public`` returns just id/name/color/has_pin/kid for pre-login lists.
Failed PIN attempts are limited per resident by ``verify``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path

VERSION = 1
MAX_RESIDENTS = 12
MAX_FAILS, LOCK_S = 5, 300.0
_N, _R, _P = 16384, 8, 1


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


class Residents:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.items: dict[str, dict] = {}
        self._fails: dict[str, list[float]] = {}
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if data.get("version") == VERSION:
                self.items = {k: v for k, v in data.get("residents", {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass

    def add(self, name: str, color: str = "#3584e4", kid: bool = False) -> str | None:
        name = (name or "").strip()[:30]
        if not name or len(self.items) >= MAX_RESIDENTS or any(r["name"].lower() == name.lower() for r in self.items.values()):
            return None
        rid = "r" + secrets.token_hex(6)
        self.items[rid] = {"name": name, "color": color[:9], "kid": bool(kid), "pin": None}
        self._save()
        return rid

    def rename(self, rid: str, name: str) -> bool:
        name = (name or "").strip()[:30]
        if rid not in self.items or not name or any(k != rid and r["name"].lower() == name.lower() for k, r in self.items.items()):
            return False
        self.items[rid]["name"] = name
        self._save()
        return True

    def set_pin(self, rid: str, pin: str | None) -> bool:
        r = self.items.get(rid)
        if r is None:
            return False
        if pin is None:
            r["pin"] = None
        elif pin.isdigit() and 4 <= len(pin) <= 8:
            salt = os.urandom(16)
            r["pin"] = {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(_hash(pin, salt)).decode(),
                        "n": _N, "r": _R, "p": _P}
        else:
            return False
        self._fails.pop(rid, None)
        self._save()
        return True

    def delete(self, rid: str) -> bool:
        gone = self.items.pop(rid, None) is not None
        self._fails.pop(rid, None)
        if gone:
            self._save()
        return gone

    def verify(self, rid: str, pin: str | None, now: float) -> tuple[bool, str]:
        r = self.items.get(rid)
        if r is None:
            return False, "That person isn't in this house."
        if r["pin"] is None:
            return True, ""
        recent = [t for t in self._fails.get(rid, []) if now - t < LOCK_S]
        if len(recent) >= MAX_FAILS:
            return False, "Too many tries. Wait a few minutes."
        salt = base64.b64decode(r["pin"]["salt"])
        ok = isinstance(pin, str) and hmac.compare_digest(_hash(pin, salt), base64.b64decode(r["pin"]["hash"]))
        if ok:
            self._fails.pop(rid, None)
            return True, ""
        self._fails[rid] = recent + [now]
        return False, "That PIN didn't match. Try again."

    def public(self) -> list[dict]:
        return [{"id": k, "name": v["name"], "color": v["color"], "has_pin": v["pin"] is not None, "kid": v["kid"]}
                for k, v in sorted(self.items.items(), key=lambda kv: kv[1]["name"].lower())]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".residents")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": VERSION, "residents": self.items}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
