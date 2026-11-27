"""Share-to-SmoothCast (#382). Pure policy for the PWA share target and POST /share.

``share_target`` is the manifest entry; ``guard`` rejects cross-origin / unauthenticated / non-multipart
posts; ``classify`` turns the shared files + text/url into accepted items and plain messages (URLs go
through ``guest_url``); ``Pending`` keeps a share across the login redirect (short TTL, single use).
"""
from __future__ import annotations

import json
import re
import secrets
from urllib.parse import urlsplit

import guest_url

MAX_FILES, PENDING_TTL_S, MAX_PENDING = 20, 600, 50
MEDIA_PREFIXES = ("video/", "audio/", "image/")
ACCEPT = ["video/*", "audio/*", "image/*"]
MSG_OFFLINE = "Connect to the house Wi-Fi to share."
_URL = re.compile(r"https?://\S+", re.I)


def share_target() -> dict:
    return {"action": "/share", "method": "POST", "enctype": "multipart/form-data",
            "params": {"title": "title", "text": "text", "url": "url", "files": [{"name": "media", "accept": ACCEPT}]}}


def manifest_with_share(manifest_json: str) -> str:
    d = json.loads(manifest_json)
    d["share_target"] = share_target()
    return json.dumps(d, sort_keys=True)


def valid_share_target(entry: dict) -> bool:
    """Schema check mirroring what Chromium requires."""
    try:
        p = entry["params"]
        files = p.get("files", [])
        return (entry["action"].startswith("/") and entry["method"] == "POST" and entry["enctype"] == "multipart/form-data"
                and all(isinstance(f.get("name"), str) and f.get("accept") for f in files)
                and any(p.get(k) for k in ("title", "text", "url")))
    except (KeyError, AttributeError, TypeError):
        return False


def guard(method: str, origin: str | None, host: str, authenticated: bool, content_type: str = "multipart/form-data",
          on_lan: bool = True) -> tuple[int, str]:
    """(status, message). 200 means proceed."""
    if not on_lan:
        return 403, MSG_OFFLINE
    if method.upper() != "POST":
        return 405, "Share from your phone's share sheet."
    if not origin or urlsplit(origin).netloc.lower() != (host or "").lower():
        return 403, "That share didn't come from SmoothCast."          # cross-origin or missing Origin
    if not content_type.lower().startswith("multipart/form-data"):
        return 415, "That share couldn't be read."
    if not authenticated:
        return 401, "Join the room to share."
    return 200, ""


def classify(files: list[dict], text: str = "", url: str = "", title: str = "") -> dict:
    """files: [{name, type, size}]. -> {items:[{kind,...}], messages:[str]}."""
    items, msgs = [], []
    for f in (files or [])[:MAX_FILES]:
        t = (f.get("type") or "").lower()
        if t.startswith(MEDIA_PREFIXES):
            items.append({"kind": t.split("/")[0], "name": (f.get("name") or "shared")[:120], "size": int(f.get("size") or 0)})
        else:
            msgs.append(f"“{(f.get('name') or 'That file')[:60]}” isn't a video, song or photo SmoothCast can play.")
    if len(files or []) > MAX_FILES:
        msgs.append(f"Only the first {MAX_FILES} files were shared.")
    cand = (url or "").strip() or (m.group(0).rstrip(").,") if (m := _URL.search(text or "")) else "")
    if cand:
        canon, why = guest_url.validate(cand)
        if canon:
            items.append({"kind": "url", "url": canon, "title": (title or "")[:120]})
        else:
            msgs.append(why)
    elif not items and not msgs:
        msgs.append("Nothing to share was found.")
    return {"items": items, "messages": msgs}


class Pending:
    """Share held across the join/login redirect. Single use, bounded, expiring."""

    def __init__(self, clock=None) -> None:
        import time
        self.clock, self.d = clock or time.time, {}

    def stash(self, share: dict) -> str:
        now = self.clock()
        self.d = {k: v for k, v in self.d.items() if now - v[0] < PENDING_TTL_S}
        while len(self.d) >= MAX_PENDING:
            self.d.pop(next(iter(self.d)))
        tok = secrets.token_urlsafe(16)
        self.d[tok] = (now, share)
        return tok

    def resume(self, tok: str) -> dict | None:
        ent = self.d.pop(tok, None)
        return ent[1] if ent and self.clock() - ent[0] < PENDING_TTL_S else None
