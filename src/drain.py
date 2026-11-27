"""Graceful drain state machine (#426). Pure; every side effect is an injected action.

Order is the contract: local playback is stopped ONLY after the target is started, confirmed ready and the
receiver has been switched to it. Any failure keeps local running until the inhibitor deadline, then the
no-target path saves the resume point and tells remotes. Mesh message: ``node.leaving {in_seconds}``.
"""
from __future__ import annotations

DEADLINE_S = 15.0


def fmt_time(sec) -> str:
    s = max(0, int(sec or 0))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def sleep_message(node: str, pos) -> str:
    return f"{node} is going to sleep; playback stopped at {fmt_time(pos)}."


def leaving(in_seconds: float = DEADLINE_S) -> dict:
    return {"type": "node.leaving", "in_seconds": max(0, min(int(in_seconds), 60))}


def pick_target(nodes: list[dict], key: str) -> dict | None:
    """Awake, encode-capable, and can reach the file (has it or #422 proxy works). Best: has file, then lowest load."""
    ok = [n for n in nodes if n.get("awake") and n.get("encode") and (n.get("has_file") or n.get("proxy_ok"))]
    return min(ok, key=lambda n: (not n.get("has_file"), n.get("load", 0.0), n["id"]), default=None)


def drain(stream: dict, nodes: list[dict], act: dict, inhibitor, clock, node_name: str = "This computer") -> dict:
    """``act``: start(target, pos)->bool, ready(target)->bool, switch(target)->bool, stop_local(), save_resume(pos), notify(msg), announce(msg).
    -> {"outcome": "handed_over"|"stopped", "target"?, "steps": [...]}"""
    steps: list[str] = []
    pos = stream.get("position", 0)
    inhibitor.acquire("Handing playback to another SmoothCast computer")
    t0 = clock()
    try:
        _try(act, "announce", leaving(DEADLINE_S))
        for target in _targets(nodes, stream.get("key")):
            if clock() - t0 >= DEADLINE_S or inhibitor.expired():
                steps.append("deadline")
                break
            steps.append(f"start:{target['id']}")
            if not _try(act, "start", target, pos):
                continue
            if clock() - t0 >= DEADLINE_S or not _try(act, "ready", target):
                steps.append(f"not_ready:{target['id']}")
                continue
            steps.append(f"switch:{target['id']}")
            if not _try(act, "switch", target):
                continue
            steps.append("stop_local")
            _try(act, "stop_local")
            return {"outcome": "handed_over", "target": target["id"], "steps": steps}
        steps.append("no_target")
        _try(act, "save_resume", pos)
        _try(act, "notify", sleep_message(node_name, pos))
        _try(act, "stop_local")
        return {"outcome": "stopped", "steps": steps}
    finally:
        inhibitor.release()


def _targets(nodes, key):
    rest = list(nodes)
    while True:
        t = pick_target(rest, key)
        if t is None:
            return
        rest = [n for n in rest if n["id"] != t["id"]]
        yield t


def _try(act, name, *args) -> bool:
    try:
        return bool(act[name](*args)) if name in ("start", "ready", "switch") else (act[name](*args), True)[1]
    except Exception:
        return False
