"""Episodic content recognition and up-next logic (#368). Pure.

``parse(name, tags)`` -> {show, season, episode, episode_end, title} or None.
Tags win over filename patterns; ambiguous names return None (stay in Films).
``group`` builds Show > Season > Episode; ``next_episode`` skips blocked items;
``Autoplay`` implements the cancellable countdown and "still watching?" rule.
"""
from __future__ import annotations

import re

_SXE = re.compile(r"(?P<show>.*?)[\s._-]*[Ss](?P<s>\d{1,2})[\s._-]*[Ee](?P<e>\d{1,3})(?:[\s._-]*(?:-|[Ee])[\s._-]*[Ee]?(?P<e2>\d{1,3}))?(?P<rest>.*)")
_NXN = re.compile(r"(?P<show>.*?)[\s._-]+(?P<s>\d{1,2})x(?P<e>\d{2,3})(?P<rest>(?:[\s._-].*)?)$", re.I)
_LONG = re.compile(r"(?P<show>.*?)[\s._-]*Season[\s._-]*(?P<s>\d{1,2})[\s._-]*Episode[\s._-]*(?P<e>\d{1,3})(?P<rest>.*)", re.I)
_ABS = re.compile(r"(?P<show>.*?[A-Za-z].*?)\s+-\s+(?P<e>\d{2,4})(?:v\d)?(?P<rest>(?:\s.*)?)$")
_JUNK = re.compile(r"[\s._-]*(?:\d{3,4}p|x26[45]|h\.?26[45]|hevc|web[-.]?dl|webrip|bluray|brrip|hdtv|aac|ac3|dts|10bit|\[.*?\]|\(.*?\)).*$", re.I)
_EXT = re.compile(r"\.(mkv|mp4|avi|m4v|mov|ts|webm)$", re.I)


def _clean(s: str) -> str:
    s = re.sub(r"[._]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -")


def _title(rest: str) -> str:
    return _clean(_JUNK.sub("", rest or ""))


def parse(name: str, tags: dict | None = None) -> dict | None:
    t = tags or {}
    try:
        if t.get("show") and t.get("season") is not None and t.get("episode") is not None:
            return {"show": str(t["show"]).strip(), "season": int(t["season"]), "episode": int(t["episode"]),
                    "episode_end": None, "title": str(t.get("title") or "")}
    except (TypeError, ValueError):
        pass
    base = re.sub(r"^\s*\[[^\]]*\]\s*", "", _EXT.sub("", name.rsplit("/", 1)[-1]))
    for rx in (_SXE, _LONG, _NXN):
        m = rx.fullmatch(base) or rx.match(base)
        if m and _clean(m.group("show")):
            g = m.groupdict()
            e2 = int(g["e2"]) if g.get("e2") and int(g["e2"]) > int(g["e"]) else None
            return {"show": _clean(g["show"]), "season": int(g["s"]), "episode": int(g["e"]),
                    "episode_end": e2, "title": _title(g["rest"])}
    m = _ABS.fullmatch(base)
    if m and not re.search(r"\b(19|20)\d{2}\b", m.group("show")):
        return {"show": _clean(m.group("show")), "season": 1, "episode": int(m.group("e")), "episode_end": None,
                "title": _title(m.group("rest"))}
    return None


def group(items: list[dict]) -> tuple[dict, list[dict]]:
    """items: {key, name, tags?}. Returns ({show: {season: [eps sorted]}}, films)."""
    shows: dict[str, dict[int, list[dict]]] = {}
    films = []
    for it in items:
        p = parse(it.get("name", ""), it.get("tags"))
        if p is None:
            films.append(it)
            continue
        shows.setdefault(p["show"].lower(), {}).setdefault(p["season"], []).append({**p, "key": it["key"]})
    for seasons in shows.values():
        for eps in seasons.values():
            eps.sort(key=lambda e: e["episode"])
    return shows, films


def flat(seasons: dict[int, list[dict]]) -> list[dict]:
    return [e for s in sorted(seasons, key=lambda x: (x == 0, x)) for e in seasons[s]]   # specials last


def next_episode(seasons: dict[int, list[dict]], current_key: str, allowed=lambda e: True) -> dict | None:
    eps = flat(seasons)
    idx = next((i for i, e in enumerate(eps) if e["key"] == current_key), None)
    if idx is None:
        return None
    for e in eps[idx + 1:]:
        if allowed(e):
            return e
        return None                      # never silently skip over a blocked item to a later one
    return None


class Autoplay:
    COUNTDOWN_S, STILL_WATCHING_AFTER = 10, 3

    def __init__(self, ask_still_watching: bool = True) -> None:
        self.cancelled = False
        self.chained = 0
        self.ask = ask_still_watching

    def offer(self, nxt: dict | None) -> dict | None:
        if self.cancelled or nxt is None:
            return None
        if self.ask and self.chained >= self.STILL_WATCHING_AFTER:
            return {"kind": "still_watching", "message": "Are you still watching?"}
        label = f"S{nxt['season']:02d}E{nxt['episode']:02d}" + (f" '{nxt['title']}'" if nxt.get("title") else "")
        return {"kind": "countdown", "seconds": self.COUNTDOWN_S, "message": f"Next: {label} in {self.COUNTDOWN_S}…", "key": nxt["key"]}

    def started_automatically(self) -> None:
        self.chained += 1

    def interaction(self) -> None:
        self.chained = 0

    def cancel(self) -> None:
        self.cancelled = True
