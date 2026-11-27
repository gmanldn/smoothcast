"""Kid profile limits (#364): rating cap, bedtime windows, daily budget. Pure; clock passed in.

Ratings: G < PG < 12 < 15 < 18; Unrated is blocked by default. Items with
conflicting ratings use the strictest. Bedtime windows may cross midnight and
are evaluated in the *local* wall-clock time supplied by the caller (so DST is
handled by the caller's zone). Enforcement only gates *starting* playback; it
never stops a running film. Pause/stop/volume-down are always allowed.
"""
from __future__ import annotations

from datetime import datetime

ORDER = ("G", "PG", "12", "15", "18")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ALWAYS_OK = {"pause", "stop", "volume_down"}
START_ACTIONS = {"play", "next", "previous", "queue_play", "play_now"}


def _rank(r: str | None) -> int | None:
    return ORDER.index(r) if r in ORDER else None


def strictest(ratings: list[str | None]) -> str | None:
    known = [r for r in (ratings or []) if r in ORDER]
    return max(known, key=ORDER.index) if known else None


def rating_allowed(item_ratings: list[str | None], limits: dict) -> tuple[bool, str]:
    cap = _rank(limits.get("max_rating"))
    if cap is None:
        return True, ""                                   # no cap configured
    item = strictest(item_ratings)
    if item is None:
        return (limits.get("unrated", "block") != "block"), "This hasn't been rated, so it's hidden for this profile."
    return (ORDER.index(item) <= cap), "Not available for this profile."


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_bedtime(limits: dict, local: datetime) -> bool:
    """True if ``local`` falls inside today's window, or a previous day's window that spills past midnight."""
    now = local.hour * 60 + local.minute
    today, yesterday = DAYS[local.weekday()], DAYS[(local.weekday() - 1) % 7]
    sched = limits.get("bedtime") or {}
    for start, end in (sched.get(today) or []):
        s, e = _minutes(start), _minutes(end)
        if (s <= now < e) if s < e else (now >= s):
            return True
    for start, end in (sched.get(yesterday) or []):
        s, e = _minutes(start), _minutes(end)
        if s >= e and now < e:                            # the after-midnight tail
            return True
    return False


def decide(action: str, name: str, limits: dict, local: datetime, *, item_ratings: list | None = None,
           used_minutes: float = 0.0, override: bool = False) -> tuple[bool, str]:
    if action in ALWAYS_OK or action not in START_ACTIONS:
        return True, ""
    if override:                                          # one-shot adult override, caller logs and clears it
        return True, ""
    if in_bedtime(limits, local):
        return False, f"It's past bedtime on {name}'s profile."
    budget = limits.get("budget_minutes")
    if isinstance(budget, (int, float)) and used_minutes >= budget:
        return False, f"{name}'s screen time for today is used up."
    if item_ratings is not None:
        ok, why = rating_allowed(item_ratings, limits)
        if not ok:
            return False, why
    return True, ""


def filter_listing(items: list[dict], limits: dict) -> list[dict]:
    """Kid browse view: blocked items are absent, not greyed out."""
    return [i for i in items if rating_allowed(list(i.get("ratings") or []), limits)[0]]
