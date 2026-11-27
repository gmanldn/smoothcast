"""Guest passes (#374): time-limited, scoped, QR-friendly invites. Pure + atomic JSON.

Token: 128-bit random, only its SHA-256 is stored. Scopes: queue < music/remote < full.
``allowed(scope, action, media_kind)`` is the server-side permission table; unknown actions are denied.
Every request re-checks ``validate`` so expiry/revocation takes effect immediately.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

VERSION = 1
SCOPES = ("queue", "music", "remote", "full")
MAX_PASSES = 50
MAX_TTL_S = 7 * 86400

_QUEUE = {"queue_add", "queue_reorder", "queue_remove_own", "vote"}
_TRANSPORT = {"play", "pause", "stop", "seek", "next", "previous", "volume"}
_HOST_ONLY = {"upload", "settings", "revoke", "pairing", "receiver_select", "pass_create", "library_manage"}
TABLE: dict[str, set[str]] = {
    "queue": set(_QUEUE),
    "music": set(_QUEUE),                       # same verbs, audio items only (see allowed())
    "remote": _QUEUE | _TRANSPORT,
    "full": _QUEUE | _TRANSPORT | {"upload", "receiver_select"},
}


def allowed(scope: str, action: str, media_kind: str | None = None) -> bool:
    if action in _HOST_ONLY - TABLE.get(scope, set()):
        return False
    if action not in TABLE.get(scope, ()):
        return False
    if scope == "music" and action in ("queue_add",) and media_kind != "audio":
        return False
    return True


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Passes:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.items: dict[str, dict] = {}                # keyed by token hash
        if self.path:
            try:
                d = json.loads(self.path.read_text("utf-8"))
                if d.get("version") == VERSION:
                    self.items = {k: v for k, v in d.get("passes", {}).items() if isinstance(v, dict)}
            except (OSError, ValueError, AttributeError):
                pass

    def create(self, label: str, scope: str, ttl_s: float, max_uses: int, now: float, created_by: str = "host") -> tuple[str | None, str]:
        """Returns (token, "") — the only time the token exists in clear — or (None, reason)."""
        if scope not in SCOPES or not (0 < ttl_s <= MAX_TTL_S) or not (1 <= max_uses <= 100):
            return None, "Invalid pass settings."
        self._expire(now)
        if len(self.items) >= MAX_PASSES:
            return None, "Too many active passes."
        token = secrets.token_urlsafe(16)               # 128 bits
        self.items[_h(token)] = {"id": "p" + secrets.token_hex(4), "label": (label or "Guest pass")[:40], "scope": scope,
                                 "expires_at": now + ttl_s, "max_uses": int(max_uses), "uses": [], "created_by": created_by}
        self._save()
        return token, ""

    def _expire(self, now: float) -> None:
        for k in [k for k, v in self.items.items() if v["expires_at"] <= now]:
            del self.items[k]

    def redeem(self, token: str, device: str, now: float) -> tuple[dict | None, str]:
        p = self.items.get(_h(token or ""))
        if p is None or p["expires_at"] <= now:
            return None, "This pass has expired. Ask the host for a new one."
        if device not in p["uses"]:
            if len(p["uses"]) >= p["max_uses"]:
                return None, "This pass is full. Ask the host for another."
            p["uses"].append(device)
            self._save()
        return {"id": p["id"], "scope": p["scope"], "label": p["label"], "expires_at": p["expires_at"]}, ""

    def validate(self, token: str, device: str, now: float) -> dict | None:
        """Per-request check: revoked/expired/unknown or device never redeemed -> None."""
        p = self.items.get(_h(token or ""))
        if p is None or p["expires_at"] <= now or device not in p["uses"]:
            return None
        return {"id": p["id"], "scope": p["scope"]}

    def revoke(self, pass_id: str) -> bool:
        for k, v in list(self.items.items()):
            if v["id"] == pass_id:
                del self.items[k]
                self._save()
                return True
        return False

    def listing(self, now: float) -> list[dict]:
        return [{"id": v["id"], "label": v["label"], "scope": v["scope"], "expires_in": max(0, int(v["expires_at"] - now)),
                 "devices": len(v["uses"]), "max_uses": v["max_uses"]} for v in self.items.values() if v["expires_at"] > now]

    @staticmethod
    def join_url(host: str, token: str) -> str:
        return f"https://{host}/join#pass={token}"        # fragment: never sent to servers or proxy logs

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".passes")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": VERSION, "passes": self.items}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
