"""Shared internet radio stations and podcast feeds (#380). Pure parsing + policy; no network.

``parse_feed`` accepts RSS 2.0 / Atom with enclosures. Hostile XML is rejected before parsing: any
DOCTYPE/ENTITY declaration, >10 MB, or nesting deeper than 20. URLs reuse ``guest_url`` safety rules.
``Subscriptions`` caps feeds (50) and episodes (500), keeps per-resident progress and the New-episodes
badge, and ``conditional_headers`` / ``handle_response`` implement ETag / If-Modified-Since refresh.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import guest_url

MAX_BYTES, MAX_DEPTH = 10 * 1024 * 1024, 20
MAX_FEEDS, MAX_EPISODES = 50, 500
REFRESH_S = 2 * 3600
AUDIO_TYPES = ("audio/", "application/ogg", "application/vnd.apple.mpegurl", "application/x-mpegurl")
_BAD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)
_AUDIO_EXT = re.compile(r"\.(mp3|aac|m4a|ogg|opus|m3u8|flac|wav)(\?|$)", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _depth_ok(root: ET.Element) -> bool:
    stack = [(root, 1)]
    while stack:
        el, d = stack.pop()
        if d > MAX_DEPTH:
            return False
        stack.extend((c, d + 1) for c in el)
    return True


def _dur(text: str | None) -> float | None:
    if not text:
        return None
    try:
        parts = [float(p) for p in text.strip().split(":")]
    except ValueError:
        return None
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts))) if 1 <= len(parts) <= 3 else None


def parse_feed(data: bytes) -> tuple[dict | None, str]:
    if not isinstance(data, (bytes, bytearray)):
        return None, "Not a feed."
    if len(data) > MAX_BYTES:
        return None, "That feed is too large."
    if _BAD.search(data[:200_000]) or _BAD.search(data):
        return None, "That feed uses features SmoothCast blocks for safety."
    try:
        root = ET.fromstring(bytes(data))
    except ET.ParseError:
        return None, "That doesn't look like a podcast feed."
    if not _depth_ok(root):
        return None, "That feed is too deeply nested."
    kind = _local(root.tag)
    items = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    title_el = next((e for e in root.iter() if _local(e.tag) == "title"), None)
    eps = []
    for it in items[:MAX_EPISODES]:
        enc, guid, title, pub, dur = None, None, "", None, None
        for c in it:
            n = _local(c.tag)
            if n == "title":
                title = (c.text or "").strip()[:200]
            elif n in ("guid", "id"):
                guid = (c.text or "").strip()[:300]
            elif n == "enclosure" or (n == "link" and c.get("rel") == "enclosure"):
                url = c.get("url") or c.get("href")
                typ = (c.get("type") or "").lower()
                if url and (typ.startswith(AUDIO_TYPES) or _AUDIO_EXT.search(url)):
                    enc = url
            elif n in ("pubdate", "published", "updated"):
                try:
                    pub = parsedate_to_datetime(c.text).timestamp()
                except (TypeError, ValueError):
                    pub = None
            elif n == "duration":
                dur = _dur(c.text)
        if enc:
            eps.append({"guid": guid or enc, "title": title or "Episode", "url": enc, "published": pub, "duration": dur})
    if kind not in ("rss", "feed", "rdf") or not eps and not items:
        return None, "That doesn't look like a podcast feed."
    eps.sort(key=lambda e: -(e["published"] or 0))
    return {"title": ((title_el.text if title_el is not None else "") or "Podcast").strip()[:120], "episodes": eps}, ""


def validate_station(url: str, allow_private: bool = False) -> tuple[str | None, str]:
    canon, why = guest_url.validate(url)
    if canon is None and allow_private:
        return None, why                              # even host opt-in doesn't relax scheme/credential rules here
    return canon, why


class Subscriptions:
    def __init__(self) -> None:
        self.stations: dict[str, dict] = {}
        self.feeds: dict[str, dict] = {}              # url -> {title, episodes, etag, modified, checked, seen:set}
        self.progress: dict[tuple[str, str], float] = {}   # (resident, guid) -> seconds

    def add_station(self, name: str, url: str) -> tuple[bool, str]:
        canon, why = validate_station(url)
        if canon is None:
            return False, why
        self.stations[canon] = {"name": (name or canon)[:60], "url": canon}
        return True, ""

    def add_feed(self, url: str) -> tuple[str | None, str]:
        canon, why = guest_url.validate(url)
        if canon is None:
            return None, why
        if canon not in self.feeds and len(self.feeds) >= MAX_FEEDS:
            return None, "That's the most podcasts SmoothCast can follow."
        self.feeds.setdefault(canon, {"title": "", "episodes": [], "etag": None, "modified": None, "checked": float("-inf"), "seen": set()})
        return canon, ""

    def due(self, now: float) -> list[str]:
        return [u for u, f in self.feeds.items() if now - f["checked"] >= REFRESH_S]

    def conditional_headers(self, url: str) -> dict:
        f, h = self.feeds.get(url) or {}, {}
        if f.get("etag"):
            h["If-None-Match"] = f["etag"]
        if f.get("modified"):
            h["If-Modified-Since"] = f["modified"]
        return h

    def handle_response(self, url: str, status: int, headers: dict, body: bytes, now: float) -> tuple[bool, str]:
        f = self.feeds.get(url)
        if f is None:
            return False, "Unknown feed."
        f["checked"] = now
        if status == 304:
            return True, ""                           # unchanged: nothing to parse
        if status != 200:
            return False, "The feed couldn't be refreshed."
        parsed, why = parse_feed(body)
        if parsed is None:
            return False, why
        f["title"], f["episodes"] = parsed["title"], parsed["episodes"][:MAX_EPISODES]
        low = {k.lower(): v for k, v in (headers or {}).items()}
        f["etag"], f["modified"] = low.get("etag"), low.get("last-modified")
        return True, ""

    def new_count(self, url: str) -> int:
        f = self.feeds.get(url) or {}
        return sum(1 for e in f.get("episodes", []) if e["guid"] not in f.get("seen", ()))

    def total_new(self) -> int:
        return sum(self.new_count(u) for u in self.feeds)

    def mark_seen(self, url: str) -> None:
        f = self.feeds.get(url)
        if f:
            f["seen"] = {e["guid"] for e in f["episodes"]}

    def set_progress(self, resident: str, guid: str, seconds: float) -> None:
        if resident:
            self.progress[(resident, guid)] = max(0.0, float(seconds))

    def get_progress(self, resident: str | None, guid: str) -> float:
        return self.progress.get((resident or "", guid), 0.0)
