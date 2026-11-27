"""Offline download rules and tidy planning (#369). Pure; the caller deletes.

``admit`` enforces the free-space rule (size + 500 MB). ``tidy`` returns what to
delete and the "Tidied N episodes" notice from per-download rules:
``{"remove_after": None|"immediately"|days, "keep_next": None|N, "unwatched_only": bool}``.
``reconcile`` marks entries the browser evicted as needs_redownload (never "available").
``Token`` helpers: short-lived download tokens bound to a session.
"""
from __future__ import annotations

import hashlib
import hmac

RESERVE = 500 * 1024 * 1024
TOKEN_TTL_S = 600
DAY = 86400.0


def meter(used: int, free: int) -> str:
    g = lambda b: f"{b / 1e9:.1f} GB"
    return f"Using {g(used)} of {g(used + free)} free."


def admit(size: int, free: int) -> tuple[bool, str]:
    if size + RESERVE > free:
        need = (size + RESERVE - free) / 1e9
        return False, f"Not enough space on this device. Free up {need:.1f} GB and try again."
    return True, ""


def eligible(items: list[dict], rule: dict, watched: set[str]) -> list[dict]:
    """Which episodes to fetch: unwatched-only filter, then keep the next N in order."""
    out = [i for i in items if not (rule.get("unwatched_only") and i["key"] in watched)]
    n = rule.get("keep_next")
    return out[:n] if isinstance(n, int) and n > 0 else out


def tidy(downloads: list[dict], rule: dict, watched: dict[str, float], now: float) -> tuple[list[str], str]:
    """downloads: {key,...}; watched: key -> time finished. Returns (keys to delete, notice)."""
    after = rule.get("remove_after")
    gone = []
    for d in downloads:
        t = watched.get(d["key"])
        if t is None or after is None:
            continue
        if after == "immediately" or now - t >= float(after) * DAY:
            gone.append(d["key"])
    n = len(gone)
    return gone, (f"Tidied {n} episode{'s' if n != 1 else ''}" if n else "")


def reconcile(manifest: dict[str, dict], present: set[str]) -> dict[str, dict]:
    """Browser may evict storage: anything not actually present is marked, never claimed available."""
    out = {}
    for k, v in manifest.items():
        out[k] = v if k in present else {**v, "state": "needs_redownload"}
    return out


def range_header(have: int, total: int) -> str | None:
    return None if have >= total else f"bytes={max(0, have)}-"


def sign(secret: bytes, content_key: str, session: str, now: float) -> str:
    exp = int(now) + TOKEN_TTL_S
    mac = hmac.new(secret, f"{content_key}|{session}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{mac}"


def verify(secret: bytes, token: str, content_key: str, session: str, now: float) -> bool:
    try:
        exp_s, mac = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    good = hmac.new(secret, f"{content_key}|{session}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return now <= exp and hmac.compare_digest(mac, good)
