"""GTK-free crossfade transition planner (#348). Pure.

``plan`` decides, per boundary, whether to overlap (equal-power) or fall back
to a standard transition with a reason. It never starts a second receiver
command: the overlap happens inside one continuous audio stream. The plan is
bound to the expected queue revision and next item id, so a reorder, skip or
setting change invalidates it.
"""
from __future__ import annotations

import math

MIN_S, MAX_S, SUGGESTED_S = 1.0, 12.0, 3.0
PREWARM_MARGIN_S = 8.0           # decode next track this long before the overlap starts
SHORTEST_TRACK_FRACTION = 0.5    # overlap may use at most half of the shorter track


def clamp_seconds(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return SUGGESTED_S
    return SUGGESTED_S if v != v else max(MIN_S, min(MAX_S, v))


def gains(t: float) -> tuple[float, float]:
    """Equal-power (out, in) gains for fade progress t in 0..1."""
    t = max(0.0, min(1.0, t))
    return math.cos(t * math.pi / 2), math.sin(t * math.pi / 2)


def plan(current: dict, nxt: dict | None, *, enabled: bool, seconds: float = SUGGESTED_S,
         rate: float = 1.0, queue_revision: int = 0, receiver_ok: bool = True) -> dict:
    """current/next: {id, kind: 'music'|'video', duration: float|None}. Returns the transition."""
    def standard(reason: str) -> dict:
        return {"mode": "standard", "reason": reason, "queue_revision": queue_revision}
    if not enabled:
        return standard("Crossfade is off.")
    if nxt is None:
        return standard("Nothing is queued next.")
    if current.get("kind") != "music" or nxt.get("kind") != "music":
        return standard("Crossfade only applies between music tracks.")
    cur_d, nxt_d = current.get("duration"), nxt.get("duration")
    if not all(isinstance(d, (int, float)) and d > 0 for d in (cur_d, nxt_d)):
        return standard("Track length is unknown.")
    if not receiver_ok:
        return standard("This TV can't be relied on for a smooth overlap.")
    if not isinstance(rate, (int, float)) or not 0.5 <= rate <= 2.0:
        return standard("Unsupported playback speed.")
    fade = min(clamp_seconds(seconds), SHORTEST_TRACK_FRACTION * min(cur_d, nxt_d))
    if fade < MIN_S:
        return standard("A track is too short to overlap.")
    start = cur_d - fade * rate                      # source time where the fade begins
    return {"mode": "crossfade", "reason": "", "fade_s": round(fade, 2), "start_at": round(start, 2),
            "prewarm_at": round(max(0.0, start - PREWARM_MARGIN_S), 2),
            "next_id": nxt.get("id"), "queue_revision": queue_revision}


def still_valid(p: dict, queue_revision: int, next_id: object) -> bool:
    """Re-check before executing: reorder/skip/revision change cancels the overlap."""
    return p.get("mode") == "crossfade" and p.get("queue_revision") == queue_revision and p.get("next_id") == next_id


def filter_graph(fade_s: float) -> str:
    """FFmpeg two-input overlap; equal-power curves; followed by the final peak limiter."""
    d = f"{clamp_seconds(fade_s):g}"
    return f"[0:a][1:a]acrossfade=d={d}:c1=qsin:c2=qsin,alimiter=limit=0.89:level=disabled[a]"
