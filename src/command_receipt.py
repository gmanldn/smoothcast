"""Receipt tracker for phone transport commands (#320). Pure and bounded.

A 202 only means ``accepted``. A receipt becomes ``confirmed`` only when an
observed receiver status satisfies the action's postcondition for the *same*
session generation and media; otherwise it ends ``failed`` or, past its
deadline, ``uncertain`` (never an endless spinner). Receipts from an older
generation or a revoked login are ignored.
"""
from __future__ import annotations

REJECTED, ACCEPTED, EXECUTING, CONFIRMED, FAILED, UNCERTAIN = (
    "rejected", "accepted", "executing", "confirmed", "failed", "uncertain")
TERMINAL = {REJECTED, CONFIRMED, FAILED, UNCERTAIN}
DEADLINE_S = 12.0
MAX_RECEIPTS = 64
SAFE_RETRY = {"play", "pause", "stop", "volume", "seek"}   # idempotent given a target
SEEK_TOL_S = 2.0


def satisfied(action: str, arg: object, status: dict) -> bool:
    state = status.get("state")
    if action == "play":
        return state == "PLAYING"
    if action == "pause":
        return state == "PAUSED"
    if action == "stop":
        return state in ("IDLE", "STOPPED")
    if action == "seek":
        pos = status.get("position")
        return isinstance(pos, (int, float)) and isinstance(arg, (int, float)) and abs(pos - arg) <= SEEK_TOL_S
    if action == "volume":
        vol = status.get("volume")
        return isinstance(vol, (int, float)) and isinstance(arg, (int, float)) and abs(vol - arg) <= 0.02
    return False


class Receipts:
    def __init__(self) -> None:
        self._r: dict[str, dict] = {}

    def issue(self, rid: str, action: str, arg: object, generation: object, media: object,
              now: float, accepted: bool = True, session: object = None) -> dict:
        rec = {"id": rid, "action": action, "arg": arg, "generation": generation, "media": media,
               "session": session, "status": ACCEPTED if accepted else REJECTED, "at": now,
               "retry_ok": action in SAFE_RETRY, "message": ""}
        self._r[rid] = rec
        while len(self._r) > MAX_RECEIPTS:
            self._r.pop(next(iter(self._r)))
        return rec

    def observe(self, status: dict, generation: object, media: object, now: float,
                session: object = None) -> None:
        for rec in self._r.values():
            if rec["status"] in TERMINAL:
                continue
            if rec["generation"] != generation or rec["session"] != session:
                continue                         # stale: handled by expire/supersede
            if rec["media"] != media:
                rec["status"], rec["message"] = FAILED, "A different film is playing now."
            elif satisfied(rec["action"], rec["arg"], status):
                rec["status"] = CONFIRMED
            else:
                rec["status"] = EXECUTING
        self.expire(now)

    def expire(self, now: float) -> None:
        for rec in self._r.values():
            if rec["status"] not in TERMINAL and now - rec["at"] > DEADLINE_S:
                rec["status"], rec["message"] = UNCERTAIN, "The TV did not confirm. Check it, then try again."

    def supersede(self, generation: object, session: object = None) -> None:
        """Film/session changed or login revoked: nothing pending may confirm later."""
        for rec in self._r.values():
            if rec["status"] not in TERMINAL and (rec["generation"] != generation or rec["session"] != session):
                rec["status"], rec["message"] = UNCERTAIN, "The room changed before this was confirmed."

    def get(self, rid: str) -> dict | None:
        return self._r.get(rid)
