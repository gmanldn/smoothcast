"""House health dashboard view-model (#386). Pure: heartbeat schema + rules; no I/O.

``validate`` accepts a ``node.heartbeat`` (<= 2 KB, strict fields, no paths/usernames). ``Board`` keeps
at most 200 nodes, stamps *receive* time (peer clocks are untrusted) and ``rows`` returns green/amber/red
with plain-language reasons: older version -> Update available, free < 5 GB amber / < 1 GB red,
silent > 60 s offline.
"""
from __future__ import annotations

import json
import re

MAX_BYTES, MAX_NODES, OFFLINE_S = 2048, 200, 60.0
AMBER_FREE, RED_FREE = 5 * 10**9, 1 * 10**9
_LABEL = re.compile(r"[\w .\-]{1,40}\Z")
_VER = re.compile(r"\d{1,5}\.\d{1,5}\.\d{1,5}\Z")
_PATHY = re.compile(r"(/home/|/Users/|[A-Za-z]:\\|\\\\|^/|~/|@)")
PLATFORMS = {"linux", "macos", "windows", "other"}
ENCODERS = {"cpu", "nvenc", "qsv", "vaapi", "videotoolbox", "amf"}
RANK = {"green": 0, "amber": 1, "red": 2}


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def validate(raw) -> tuple[dict | None, str]:
    """-> (clean heartbeat, "") or (None, reason)."""
    try:
        if isinstance(raw, (bytes, str)):
            if len(raw) > MAX_BYTES:
                return None, "too_large"
            raw = json.loads(raw)
        if not isinstance(raw, dict) or len(json.dumps(raw)) > MAX_BYTES:
            return None, "too_large" if isinstance(raw, dict) else "malformed"
        node, ver, plat = raw["node"], raw["version"], raw.get("platform", "other")
        if not (isinstance(node, str) and _LABEL.match(node) and not _PATHY.search(node)):
            return None, "bad_node"
        if not (isinstance(ver, str) and _VER.match(ver)):
            return None, "bad_version"
        up, act = raw.get("uptime_s", 0), raw.get("sessions", 0)
        if plat not in PLATFORMS or any(type(x) is not int or not 0 <= x <= 10**9 for x in (up, act)):
            return None, "malformed"
        roots = raw.get("roots", {})
        if not isinstance(roots, dict) or len(roots) > 16:
            return None, "malformed"
        clean_roots = {}
        for k, v in roots.items():
            if not (isinstance(k, str) and _LABEL.match(k) and not _PATHY.search(k)) or type(v) is not int or not 0 <= v <= 10**15:
                return None, "bad_root"                 # a root label, never a path
            clean_roots[k] = v
        enc = raw.get("encoders", [])
        if not isinstance(enc, list) or not all(e in ENCODERS for e in enc) or len(enc) > 8:
            return None, "malformed"
    except (KeyError, ValueError, TypeError):
        return None, "malformed"
    return {"node": node, "version": ver, "platform": plat, "uptime_s": up, "sessions": act, "roots": clean_roots, "encoders": sorted(set(enc))}, ""


def _free_text(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class Board:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.receivers: dict[str, dict] = {}

    def heartbeat(self, raw, now: float) -> tuple[bool, str]:
        hb, why = validate(raw)
        if hb is None:
            return False, why
        if hb["node"] not in self.nodes and len(self.nodes) >= MAX_NODES:
            oldest = min(self.nodes, key=lambda k: self.nodes[k]["seen"])
            del self.nodes[oldest]
        self.nodes[hb["node"]] = {**hb, "seen": now}     # receive time, not the peer's clock
        return True, ""

    def set_receiver(self, name: str, reachable: bool, now: float) -> None:
        if len(self.receivers) < 500 or name in self.receivers:
            self.receivers[name[:60]] = {"reachable": bool(reachable), "seen": now}

    def rows(self, now: float) -> list[dict]:
        newest = max((_ver(n["version"]) for n in self.nodes.values()), default=None)
        out = []
        for name, n in self.nodes.items():
            age = now - n["seen"]
            status, reasons = "green", []
            if age > OFFLINE_S:
                status, reasons = "red", [f"{name} hasn't been seen for {int(age // 60) or 1} min — is it asleep?"]
            else:
                def bump(level: str, why: str) -> None:
                    nonlocal status
                    reasons.append(why)
                    if RANK[level] > RANK[status]:
                        status = level
                if newest and _ver(n["version"]) < newest:
                    bump("amber", "Update available")
                for label, free in sorted(n["roots"].items()):
                    if free < RED_FREE:
                        bump("red", f"Disk full on {name} ({label}: {_free_text(free)} free)")
                    elif free < AMBER_FREE:
                        bump("amber", f"Disk nearly full on {name} ({label}: {_free_text(free)} free)")
            out.append({"node": name, "status": status if age <= OFFLINE_S else "red", "online": age <= OFFLINE_S, "version": n["version"],
                        "platform": n["platform"], "encoders": n["encoders"], "sessions": n["sessions"],
                        "free": {k: v for k, v in n["roots"].items()}, "last_seen_s": int(age), "reasons": reasons})
        for name, r in self.receivers.items():
            out.append({"node": name, "kind": "receiver", "status": "green" if r["reachable"] else "amber", "online": r["reachable"],
                        "reasons": [] if r["reachable"] else [f"{name} isn't answering — check it's on and on the same Wi-Fi."]})
        out.sort(key=lambda r: (-RANK[r["status"]], r["node"].lower()))
        return out

    def summary(self, now: float) -> str:
        rows = self.rows(now)
        bad = [r for r in rows if r["status"] != "green"]
        return "Everything looks good." if not bad else f"{len(bad)} of {len(rows)} need attention."
