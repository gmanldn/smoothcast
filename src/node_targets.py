"""Paired SmoothCast nodes as playback targets (#356). Pure.

``targets`` merges live peer inventory with trust and opt-in into picker rows
with honest readiness. ``Fence`` gives each node-receiver one owning session at
a time: only the owner's commands with the current epoch are accepted, so
competing rooms and stale commands are rejected without touching playback.
"""
from __future__ import annotations

READY, OFFLINE, BUSY, NOT_ENABLED, NOT_TRUSTED = "ready", "offline", "busy", "not_enabled", "not_trusted"
LABELS = {READY: "Ready", OFFLINE: "Offline", BUSY: "Playing for another room",
          NOT_ENABLED: "Playback not enabled on that computer", NOT_TRUSTED: "Not paired for control"}
STALE_S = 20.0


def targets(peers: list[dict], trusted_control: set[str], owners: dict[str, str], now: float) -> list[dict]:
    """peers: {id,name,accepts_playback,last_seen}. owners: node id -> owning session id."""
    rows = []
    for p in peers:
        pid = str(p.get("id", ""))
        seen = p.get("last_seen")
        if pid not in trusted_control:
            status = NOT_TRUSTED
        elif not isinstance(seen, (int, float)) or now - seen > STALE_S:
            status = OFFLINE
        elif not p.get("accepts_playback"):
            status = NOT_ENABLED
        elif pid in owners:
            status = BUSY
        else:
            status = READY
        rows.append({"id": pid, "name": str(p.get("name") or "Computer")[:40], "status": status,
                     "label": LABELS[status], "selectable": status == READY})
    order = {READY: 0, BUSY: 1, NOT_ENABLED: 2, OFFLINE: 3, NOT_TRUSTED: 4}
    return sorted(rows, key=lambda r: (order[r["status"]], r["name"].lower()))


class Fence:
    def __init__(self) -> None:
        self._owner: dict[str, tuple[str, int]] = {}
        self._epoch = 0

    def claim(self, node: str, session: str) -> tuple[int | None, str]:
        cur = self._owner.get(node)
        if cur and cur[0] != session:
            return None, "That computer is playing for another room."
        if cur:
            return cur[1], ""
        self._epoch += 1
        self._owner[node] = (session, self._epoch)
        return self._epoch, ""

    def accept(self, node: str, session: str, epoch: int, command: str) -> tuple[bool, str]:
        cur = self._owner.get(node)
        if cur is None or cur != (session, epoch):
            return False, "Stale or foreign command."
        return True, ""

    def release(self, node: str, session: str | None = None) -> None:
        cur = self._owner.get(node)
        if cur and (session is None or cur[0] == session):
            del self._owner[node]

    def owners(self) -> dict[str, str]:
        return {n: s for n, (s, _) in self._owner.items()}
