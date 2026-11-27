"""Synced lyrics (#378): LRC + enhanced-LRC parser, current-line lookup, per-track offsets. Pure.

Malformed lines are skipped, never fatal. Unsynced text is returned as static lines.
Sidecar choice prefers the user's language (``track.en.lrc`` > ``track.lrc``). Limits keep a hostile
file from exhausting memory: 5000 lines, 500 chars per line, 512 KB of text accepted.
"""
from __future__ import annotations

import bisect
import re
from pathlib import Path

import store

MAX_LINES, MAX_LINE_CHARS, MAX_BYTES = 5000, 500, 512 * 1024
OFFSET_MAX_S = 5.0
_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_WORD = re.compile(r"<(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?>")
_META = re.compile(r"^\[(ar|ti|al|by|offset|length|re|ve|au):(.*)\]$", re.I)


def _secs(m: str, s: str, f: str | None) -> float:
    frac = float(f"0.{f}") if f else 0.0
    return int(m) * 60 + int(s) + frac


def parse(text: str) -> dict:
    """Returns {synced, lines:[{t, text, words:[{t,text}]}], meta{}} sorted by time."""
    text = (text or "")[:MAX_BYTES].lstrip("﻿")
    lines, plain, meta, base_offset = [], [], {}, 0.0
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        mm = _META.match(raw)
        if mm:
            meta[mm.group(1).lower()] = mm.group(2).strip()
            if mm.group(1).lower() == "offset":
                try:
                    base_offset = float(mm.group(2)) / 1000.0
                except ValueError:
                    pass
            continue
        stamps = list(_TS.finditer(raw))
        # leading timestamps only (a line can repeat: [00:10.00][01:30.00] chorus)
        lead, pos = [], 0
        for s in stamps:
            if s.start() != pos:
                break
            lead.append(s)
            pos = s.end()
        body = raw[pos:].strip()
        if not lead:
            if not _TS.search(raw) and not raw.startswith("["):
                plain.append(raw[:MAX_LINE_CHARS])
            continue
        words = []
        parts = _WORD.split(body)
        if len(parts) > 1:                               # enhanced: text<ts>word<ts>word
            if parts[0].strip():
                words.append({"t": None, "text": parts[0]})
            for i in range(1, len(parts) - 3, 4):
                words.append({"t": _secs(parts[i], parts[i + 1], parts[i + 2]), "text": parts[i + 3]})
            plain_body = _WORD.sub("", body)
        else:
            plain_body = body
        plain_body = plain_body.strip()[:MAX_LINE_CHARS]
        timed = [{"t": max(0.0, w["t"] + base_offset), "text": w["text"]} for w in words if w["t"] is not None]
        for s in lead:
            lines.append({"t": max(0.0, _secs(*s.groups()) + base_offset), "text": plain_body, "words": timed})
        if len(lines) >= MAX_LINES:
            break
    if lines:
        lines.sort(key=lambda l: l["t"])
        return {"synced": True, "lines": lines[:MAX_LINES], "meta": meta}
    return {"synced": False, "lines": [{"t": None, "text": l, "words": []} for l in plain[:MAX_LINES]], "meta": meta}


def current(parsed: dict, position: float, offset: float = 0.0) -> dict:
    """Index of the line being sung at ``position`` (source seconds) and word index if timed."""
    if not parsed.get("synced"):
        return {"line": None, "word": None}
    pos = position + max(-OFFSET_MAX_S, min(OFFSET_MAX_S, offset))
    times = [l["t"] for l in parsed["lines"]]
    i = bisect.bisect_right(times, pos) - 1
    if i < 0:
        return {"line": None, "word": None}
    words = parsed["lines"][i]["words"]
    w = None
    if words:
        j = bisect.bisect_right([x["t"] for x in words], pos) - 1
        w = j if j >= 0 else None
    return {"line": i, "word": w}


def pick_sidecar(names: list[str], track_stem: str, lang: str = "en") -> str | None:
    pref = [f"{track_stem}.{lang}.lrc", f"{track_stem}.lrc"]
    low = {n.lower(): n for n in names}
    for p in pref:
        if p.lower() in low:
            return low[p.lower()]
    for n in sorted(names):                              # any other language as a last resort
        if n.lower().startswith(track_stem.lower() + ".") and n.lower().endswith(".lrc"):
            return n
    return None


def to_payload(parsed: dict) -> dict:
    return {"synced": parsed["synced"], "lines": [{"t": l["t"], "text": l["text"], "words": l["words"]} for l in parsed["lines"]]}


class Offsets:
    """±5 s per-track sync nudge, stored per content_key."""

    def __init__(self, path: Path | None = None) -> None:
        self.path, self.d = (Path(path) if path else None), {}
        if self.path:
            try:
                self.d = {k: float(v) for k, v in store.Store(self.path).read().items()}
            except (OSError, ValueError, AttributeError, TypeError):
                pass

    def get(self, key: str) -> float:
        return self.d.get(key, 0.0)

    def set(self, key: str, seconds: float) -> float:
        v = max(-OFFSET_MAX_S, min(OFFSET_MAX_S, float(seconds)))
        if v == 0.0:
            self.d.pop(key, None)
        else:
            self.d[key] = round(v, 2)
        if len(self.d) > 5000:
            self.d.pop(next(iter(self.d)))
        self._save()
        return self.d.get(key, 0.0)

    def _save(self) -> None:
        if not self.path:
            return
        # Store.write is atomic, owner-only and never raises on a full or
        # read-only disk; a failed save must not crash the GTK handler.
        store.Store(self.path).write(self.d)
