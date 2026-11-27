"""House radio (#379): endless local auto-DJ. Pure, deterministic for a given seed.

Track: {id, artist, album_artist?, album?, genres[], year?, bpm?, loudness?, rating?}. ``Station`` scores
candidates by genre overlap, artist relation, year proximity (+-5 y), tempo and loudness, then picks with a
seeded RNG from the top-K so it isn't monotonous. Hard rules: no artist twice in 3 tracks, no track twice in
4 hours, kids limits filter first, and human-queued items always play before station items.
"""
from __future__ import annotations

import random

W = {"genre": 3.0, "artist": 2.0, "year": 1.0, "tempo": 1.0, "loudness": 0.5}
ARTIST_GAP, REPEAT_S, TOP_K = 3, 4 * 3600.0, 5
FEEDBACK_STEP, FEEDBACK_MAX = 0.25, 2.0


def similarity(seed: dict, t: dict, w: dict | None = None) -> float:
    w = w or W
    sg, tg = set(map(str.lower, seed.get("genres") or [])), set(map(str.lower, t.get("genres") or []))
    genre = len(sg & tg) / len(sg | tg) if sg | tg else 0.0
    sa = {x for x in (seed.get("artist"), seed.get("album_artist")) if x}
    ta = {x for x in (t.get("artist"), t.get("album_artist")) if x}
    artist = 1.0 if sa & ta else 0.0
    year = max(0.0, 1 - abs(seed["year"] - t["year"]) / 5) if seed.get("year") and t.get("year") else 0.0
    tempo = max(0.0, 1 - abs(seed["bpm"] - t["bpm"]) / 30) if seed.get("bpm") and t.get("bpm") else 0.0
    loud = max(0.0, 1 - abs(seed["loudness"] - t["loudness"]) / 10) if seed.get("loudness") is not None and t.get("loudness") is not None else 0.0
    return w["genre"] * genre + w["artist"] * artist + w["year"] * year + w["tempo"] * tempo + w["loudness"] * loud


def seed_profile(kind: str, value: str, library: list[dict]) -> dict:
    """Seed from a track id, album, artist or genre -> a pseudo-track averaging what matches."""
    v = (value or "").lower()
    pick = {"track": lambda t: t["id"] == value, "album": lambda t: (t.get("album") or "").lower() == v,
            "artist": lambda t: (t.get("artist") or "").lower() == v or (t.get("album_artist") or "").lower() == v,
            "genre": lambda t: v in {g.lower() for g in t.get("genres") or []}}.get(kind)
    rows = [t for t in library if pick and pick(t)]
    if not rows:
        return {}
    genres = sorted({g for t in rows for g in t.get("genres") or []})
    nums = lambda k: [t[k] for t in rows if t.get(k) is not None]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    return {"artist": rows[0].get("artist") if kind in ("track", "artist", "album") else None,
            "album_artist": rows[0].get("album_artist") if kind in ("album", "artist") else None,
            "genres": genres if kind != "track" else rows[0].get("genres") or [], "year": avg(nums("year")), "bpm": avg(nums("bpm")),
            "loudness": avg(nums("loudness")), "ids": {t["id"] for t in rows}}


class Station:
    def __init__(self, seed: dict, library: list[dict], rng_seed: int = 0, persistent: bool = True) -> None:
        self.seed, self.library = seed, library
        self.rng = random.Random(rng_seed)
        self.w = dict(W)
        self.played: list[tuple[str, str, float]] = []        # (track id, artist, at)
        self.persistent = persistent

    def _allowed(self, t: dict, now: float, allow) -> bool:
        if allow is not None and not allow(t):
            return False                                       # kids limits / privacy filter first
        if any(i == t["id"] and now - at < REPEAT_S for i, _, at in self.played):
            return False
        recent = [a for _, a, _ in self.played[-ARTIST_GAP:]]
        return not (t.get("artist") and t["artist"] in recent)

    def next(self, now: float, allow=None, exclude: set[str] = frozenset()) -> dict | None:
        cands = [t for t in self.library if t["id"] not in exclude and self._allowed(t, now, allow)]
        if not cands:
            return None
        scored = sorted(((similarity(self.seed, t, self.w), t["id"], t) for t in cands), key=lambda x: (-x[0], x[1]))
        top = scored[:TOP_K]
        floor = top[0][0]
        pool = [x for x in top if x[0] >= floor * 0.5] or top[:1]
        choice = self.rng.choice(pool)[2]
        self.played.append((choice["id"], choice.get("artist") or "", now))
        self.played = self.played[-500:]
        return choice

    def feedback(self, track: dict, up: bool) -> None:
        """Thumbs adjust which features matter: reward/penalise the dimensions the track matched on."""
        d = FEEDBACK_STEP if up else -FEEDBACK_STEP
        for key in ("genre", "artist", "year", "tempo"):
            probe = similarity(self.seed, track, {k: (1.0 if k == key else 0.0) for k in W})
            if probe > 0:
                self.w[key] = max(0.0, min(W[key] + FEEDBACK_MAX, self.w[key] + d))


def queue_with_station(human: list[dict], station_items: list[dict], target_len: int = 5) -> list[dict]:
    """Human-added items always precede station items; the station only fills the tail."""
    out = list(human)
    for s in station_items:
        if len(out) >= target_len:
            break
        out.append({**s, "source": "station"})
    return out
