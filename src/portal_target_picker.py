"""Cross-node target picker model (#575): bounded read-only list and selection validation. Pure; no command is issued here.

Rows come from ``VisibilityMatrix.targets()``. Readiness is never inferred from stale hints. No IPs, paths or credentials appear.
"""
from __future__ import annotations

MAX_ROWS = 64
STALE_MS = 15_000
REASONS = {
    "busy": "In use right now",
    "stale": "Hasn't been seen recently",
    "unreachable": "Can't be reached",
    "foreign": "Playing something for someone else",
    "none": "No computer can reach it",
}


def _row(e, me: str | None) -> dict:
    ready = [s for s in e.seen_by if s.state == "ready" and s.age_ms <= STALE_MS]
    state = "ready" if ready else (e.state if e.state in REASONS else "unreachable")
    reason = ""
    if state != "ready":
        reason = REASONS["foreign"] if state == "busy" and e.owner_hint and e.owner_hint != me else REASONS.get(state, REASONS["unreachable"])
    return {"id": e.id, "name": e.name, "kind": (e.kinds or ("",))[0], "state": state, "ready": state == "ready", "reason": reason,
            "via": ready[0].node_id if ready else None}


def rows(entries, me: str | None = None, *, ready_only: bool = False) -> list[dict]:
    out = [_row(e, me) for e in entries]
    out.sort(key=lambda r: (not r["ready"], r["name"].lower(), r["id"]))
    if ready_only:
        out = [r for r in out if r["ready"]]
    return out[:MAX_ROWS]


def merge_selection(selected: str | None, new_rows: list[dict]) -> dict:
    """Keep the user's choice stable across live refreshes and reorders; never auto-switch."""
    if selected is None:
        return {"selected": None, "prompt": "Choose where to play"}
    row = next((r for r in new_rows if r["id"] == selected), None)
    if row is None:
        return {"selected": None, "prompt": "Choose where to play", "notice": "That screen or speaker disappeared."}
    return {"selected": selected, "prompt": None if row["ready"] else row["reason"], "ready": row["ready"]}


def validate(target_id, new_rows: list[dict]) -> tuple[int, dict]:
    """Stable (status, body) before any cast is attempted. 200 means 'may submit', not 'playing'."""
    if not isinstance(target_id, str) or not target_id:
        return 400, {"error": "target_required", "message": "Choose where to play."}
    row = next((r for r in new_rows if r["id"] == target_id), None)
    if row is None:
        return 409, {"error": "target_gone", "message": "That screen or speaker isn't available any more."}
    if row["state"] == "busy":
        return (403 if row["reason"] == REASONS["foreign"] else 409), {"error": "target_busy", "message": row["reason"]}
    if not row["ready"]:
        return 503, {"error": "target_not_ready", "message": row["reason"]}
    return 200, {"accepted": True, "target": target_id, "via": row["via"], "playing": False}


def status(accepted: bool, receiver_state: str | None) -> str:
    """'Playing' only after authoritative receiver confirmation; downstream idle is not playing."""
    if not accepted:
        return "Choose where to play"
    return "Playing" if receiver_state == "playing" else "Accepted — waiting for the screen to start"
