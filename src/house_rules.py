"""Quiet hours and per-room volume curfews (#375). Pure; local wall-clock datetimes are passed in.

Room rule: {days:[mon..sun], start:"HH:MM", end:"HH:MM", cap:0..1, block_new:bool}. Windows may cross
midnight (the after-midnight tail belongs to the *start* day). ``effective`` merges quiet hours with the
#330 guest ceiling (strictest wins). Host override lasts one hour and is logged by the caller.
"""
from __future__ import annotations

from datetime import datetime

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
OVERRIDE_S = 3600.0
FADE_S = 5.0


def _m(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _rule_active(rule: dict, local: datetime) -> bool:
    now = local.hour * 60 + local.minute
    today, yesterday = DAYS[local.weekday()], DAYS[(local.weekday() - 1) % 7]
    s, e = _m(rule["start"]), _m(rule["end"])
    days = rule.get("days") or DAYS
    if s < e:
        return today in days and s <= now < e
    # crosses midnight: evening part belongs to today, early-morning tail to yesterday's start day
    return (today in days and now >= s) or (yesterday in days and now < e)


def active(rules: list[dict], local: datetime) -> list[dict]:
    out = []
    for r in rules or []:
        try:
            if _rule_active(r, local):
                out.append(r)
        except (KeyError, ValueError, AttributeError, TypeError):
            continue
    return out


def effective(rules: list[dict], local: datetime, guest_ceiling: float | None = None, override_until: float | None = None,
              now: float = 0.0) -> dict:
    """Merge every active quiet rule and the guest ceiling: lowest cap wins, any block_new wins."""
    if override_until is not None and now < override_until:
        return {"cap": guest_ceiling, "block_new": False, "quiet": False, "message": "", "until": None, "override": True}
    act = active(rules, local)
    caps = [float(r["cap"]) for r in act if r.get("cap") is not None]
    cap = min(caps + ([guest_ceiling] if guest_ceiling is not None else [])) if (caps or guest_ceiling is not None) else None
    until = None
    if act:
        until = min((r["end"] for r in act), key=lambda t: _m(t)) if len(act) == 1 else max((r["end"] for r in act), key=lambda t: _m(t))
    msg = f"Quiet hours: max {round(min(caps) * 100)}% until {until.lstrip('0') if until and until[0] == '0' else until}." if act and caps else ""
    return {"cap": cap, "block_new": any(r.get("block_new") for r in act), "quiet": bool(act), "message": msg, "until": until,
            "override": False}


def clamp(requested: float, eff: dict) -> tuple[float, bool]:
    cap = eff.get("cap")
    if cap is None or requested <= cap:
        return requested, False
    return cap, True


def fade_plan(current: float, eff: dict, started_now: bool) -> dict | None:
    """At the start of quiet hours: fade a too-loud room down over FADE_S; never raise."""
    cap = eff.get("cap")
    if not started_now or cap is None or current <= cap:
        return None
    return {"from": current, "to": cap, "seconds": FADE_S}


def can_start(eff: dict, host: bool = False) -> tuple[bool, str]:
    if eff.get("block_new") and not host:
        return False, f"It's quiet time here. New playback can start again at {eff.get('until') or 'the end of quiet hours'}."
    return True, ""


def override(now: float) -> float:
    """One-click host override. Returns the expiry; the caller logs who did it."""
    return now + OVERRIDE_S


def transitioned(rules: list[dict], prev_local: datetime, local: datetime) -> bool:
    """True when quiet hours just began between two checks (drives the fade)."""
    return bool(active(rules, local)) and not active(rules, prev_local)
