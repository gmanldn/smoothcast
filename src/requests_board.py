"""Request board (#391): ask the house for a film or album that isn't in the library. Pure + atomic JSON.

Max 100 open requests; guest requests expire after 14 days; duplicates (normalised text) become +1;
requester or host may delete; fulfilling notifies the requester (kept for a returning guest identity).
No download or acquisition integration by design.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import unicodedata
from pathlib import Path

MAX_OPEN, MAX_TEXT, GUEST_TTL_S, NOTE_TTL_S = 100, 80, 14 * 86400, 30 * 86400
EMPTY = "No requests yet. Ask for something you'd like to watch or hear."


def sanitise(text) -> str:
    s = unicodedata.normalize("NFKC", text if isinstance(text, str) else "")
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return re.sub(r"\s+", " ", s).strip()[:MAX_TEXT].rstrip()


def norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", sanitise(text).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Board:
    def __init__(self, path: Path | None = None, clock=None) -> None:
        import time
        self.path, self.clock = (Path(path) if path else None), clock or time.time
        self.reqs: dict[str, dict] = {}
        self.notes: list[dict] = []
        if self.path:
            try:
                d = json.loads(self.path.read_text("utf-8"))
                self.reqs, self.notes = dict(d.get("reqs", {})), list(d.get("notes", []))
            except (OSError, ValueError, AttributeError, TypeError):
                pass

    def _expire(self) -> None:
        now = self.clock()
        for rid in [k for k, r in self.reqs.items() if r["guest"] and r["status"] == "open" and now - r["created"] > GUEST_TTL_S]:
            del self.reqs[rid]
        self.notes = [n for n in self.notes if now - n["at"] < NOTE_TTL_S]

    def add(self, text: str, who: str, guest: bool, kind: str = "film") -> dict:
        self._expire()
        clean, key = sanitise(text), norm(text)
        if not key:
            return {"ok": False, "message": "Type what you'd like to watch or hear."}
        for rid, r in self.reqs.items():
            if r["status"] == "open" and r["key"] == key:
                if who not in r["voters"]:
                    r["voters"].append(who)
                    self._save()
                return {"ok": True, "duplicate": True, "id": rid, "votes": len(r["voters"]), "message": f"Already requested — added your +1 to “{r['text']}”."}
        if sum(r["status"] == "open" for r in self.reqs.values()) >= MAX_OPEN:
            return {"ok": False, "message": "The request board is full for now."}
        rid = secrets.token_hex(6)
        self.reqs[rid] = {"id": rid, "text": clean, "key": key, "kind": kind if kind in ("film", "album", "show", "other") else "other",
                          "owner": who, "guest": bool(guest), "voters": [who], "created": self.clock(), "status": "open"}
        self._save()
        return {"ok": True, "duplicate": False, "id": rid, "votes": 1}

    def delete(self, rid: str, who: str, host: bool) -> bool:
        r = self.reqs.get(rid)
        if not r or not (host or r["owner"] == who):
            return False
        del self.reqs[rid]
        self._save()
        return True

    def fulfil(self, rid: str, title: str, host: bool = True) -> bool:
        r = self.reqs.get(rid)
        if not r or r["status"] != "open" or not host:
            return False
        r["status"] = "done"
        for v in r["voters"]:
            self.notes.append({"to": v, "text": f"Your request '{r['text']}' is ready to watch.", "title": sanitise(title), "at": self.clock()})
        del self.reqs[rid]
        self._save()
        return True

    def notifications(self, who: str) -> list[str]:
        """Returned once; a returning guest with the same identity still gets theirs (until NOTE_TTL_S)."""
        self._expire()
        mine = [n for n in self.notes if n["to"] == who]
        if mine:
            self.notes = [n for n in self.notes if n["to"] != who]
            self._save()
        return [n["text"] for n in mine]

    def listing(self) -> dict:
        self._expire()
        rows = sorted((r for r in self.reqs.values() if r["status"] == "open"), key=lambda r: (-len(r["voters"]), r["created"]))
        return {"requests": [{"id": r["id"], "text": r["text"], "kind": r["kind"], "votes": len(r["voters"]), "guest": r["guest"]} for r in rows],
                "empty": EMPTY if not rows else ""}

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".req")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"reqs": self.reqs, "notes": self.notes}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
