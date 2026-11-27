"""Movie-night picker (#392). Pure poll state + instant-runoff tally with a displayed tie seed.

Only people present at close count. Early close when every present participant has voted. Winner starts
after a cancellable 5 s countdown. ``suggest`` offers titles nobody present has seen and every present
kid's limits allow (reuses ``kids_limits.rating_allowed``).
"""
from __future__ import annotations

import random

import kids_limits

MIN_S, MAX_S, DEFAULT_S, COUNTDOWN_S, MAX_CANDIDATES = 30, 180, 60, 5, 12


def suggest(candidates: list[dict], present: list[dict], n: int = 4, seed: int = 0) -> list[dict]:
    """candidates: {id,title,ratings[]}; present: {id, kid?, limits?, seen:set}."""
    seen = set().union(*[set(p.get("seen") or ()) for p in present]) if present else set()
    kids = [p for p in present if p.get("kid")]
    ok = [c for c in candidates if c["id"] not in seen and all(kids_limits.rating_allowed(c.get("ratings") or [], k.get("limits") or {})[0] for k in kids)]
    return random.Random(seed).sample(ok, min(n, len(ok)))


def irv(ballots: list[list[str]], options: list[str], seen_counts: dict[str, int] | None = None, seed: int = 0) -> dict:
    """Instant-runoff. ballots are ranked lists. -> {winner, rounds[], votes, total, seed, tie_broken}."""
    seen_counts, rng = seen_counts or {}, random.Random(seed)
    live = [o for o in options]
    ballots = [[o for o in dict.fromkeys(b) if o in options] for b in ballots]
    ballots = [b for b in ballots if b]
    rounds, tie_broken = [], False
    if not ballots:
        return {"winner": None, "rounds": [], "votes": 0, "total": 0, "seed": seed, "tie_broken": False}

    def pick(tied: list[str]) -> str:
        nonlocal tie_broken
        tie_broken = True
        low = min(seen_counts.get(t, 0) for t in tied)
        pool = sorted(t for t in tied if seen_counts.get(t, 0) == low)
        return pool[0] if len(pool) == 1 else rng.choice(pool)

    while True:
        tally = {o: 0 for o in live}
        for b in ballots:
            top = next((o for o in b if o in live), None)
            if top:
                tally[top] += 1
        active = sum(tally.values())
        rounds.append(dict(tally))
        best = max(tally.values())
        leaders = sorted(o for o, v in tally.items() if v == best)
        if best * 2 > active or len(live) == 1 or len(leaders) == len(live):
            win = leaders[0] if len(leaders) == 1 else pick(leaders)
            return {"winner": win, "rounds": rounds, "votes": tally[win], "total": active, "seed": seed, "tie_broken": tie_broken}
        worst = min(tally.values())
        losers = sorted(o for o, v in tally.items() if v == worst)
        out = losers[0] if len(losers) == 1 else None
        if out is None:                                  # eliminate the one MORE seen, i.e. keep the fewest-seen
            hi = max(seen_counts.get(t, 0) for t in losers)
            more = sorted(t for t in losers if seen_counts.get(t, 0) == hi)
            out = more[0] if len(more) == 1 else rng.choice(more)
            tie_broken = True
        live.remove(out)


class Poll:
    def __init__(self, options: list[dict], present: list[str], now: float, seconds: float = DEFAULT_S, ranked: bool = False, seed: int = 0) -> None:
        self.options = {o["id"]: o for o in options[:MAX_CANDIDATES]}
        self.present, self.ballots = set(present), {}
        self.ranked, self.seed = ranked, seed
        self.closes_at = now + max(MIN_S, min(MAX_S, seconds))
        self.result: dict | None = None
        self.start_at: float | None = None
        self.cancelled = False

    def join(self, who: str) -> None:
        self.present.add(who)

    def leave(self, who: str) -> None:
        self.present.discard(who)

    def vote(self, who: str, ranking: list[str], now: float) -> bool:
        if self.result is not None or now >= self.closes_at or who not in self.present:
            return False
        valid = [o for o in dict.fromkeys(ranking or []) if o in self.options]
        if not valid:
            return False
        self.ballots[who] = valid if self.ranked else valid[:1]
        return True

    def due(self, now: float) -> bool:
        return self.result is None and (now >= self.closes_at or (bool(self.present) and self.present <= set(self.ballots)))

    def close(self, now: float, seen_counts: dict[str, int] | None = None) -> dict:
        if self.result is not None:
            return self.result
        counted = [b for w, b in self.ballots.items() if w in self.present]
        r = irv(counted, list(self.options), seen_counts, self.seed)
        if r["winner"] is None:
            self.result = {**r, "message": "Nobody voted.", "start": False}
        else:
            title = self.options[r["winner"]]["title"]
            self.start_at = now + COUNTDOWN_S
            self.result = {**r, "title": title, "start": True,
                           "message": f"'{title}' wins ({r['votes']} of {r['total']} votes). Starting in {COUNTDOWN_S}…",
                           "tie_note": f"Tie broken with seed {self.seed}." if r["tie_broken"] else ""}
        return self.result

    def cancel(self) -> None:
        self.cancelled = True

    def should_start(self, now: float) -> str | None:
        """Winner id once the countdown ends, unless cancelled."""
        if self.result and self.result.get("start") and not self.cancelled and self.start_at is not None and now >= self.start_at:
            return self.result["winner"]
        return None
