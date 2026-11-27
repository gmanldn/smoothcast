"""Exact-position room handoff state machine (#372). Pure; the caller performs the IO.

States: idle -> preparing -> starting -> confirming -> done | rolled_back.
The source is stopped ONLY after the target is confirmed PLAYING. A timeout rolls back and
leaves the source playing. If the source dies mid-handoff the target simply continues.
The same handoff id is idempotent. Queue and Up Next travel with the snapshot.
"""
from __future__ import annotations

IDLE, PREPARING, STARTING, CONFIRMING, DONE, ROLLED_BACK = "idle", "preparing", "starting", "confirming", "done", "rolled_back"
CONFIRM_TIMEOUT_S = 15.0
MAX_DELTA_S = 2.0


class Handoff:
    def __init__(self, handoff_id: str, source: str, target: str, snapshot: dict, now: float, *, source_name: str = "", target_name: str = "") -> None:
        self.id, self.source, self.target = handoff_id, source, target
        self.snap = snapshot                       # {media, position, rate, paused_at, queue, up_next}
        self.names = (source_name or source, target_name or target)
        self.state = PREPARING
        self.message = ""
        self.t0 = now
        self.start_wall: float | None = None
        self.start_pos = 0.0
        self.actions: list[str] = []               # audit of what the caller was told to do

    def next_action(self, now: float) -> dict | None:
        """The one thing the caller should do next, or None while waiting."""
        if self.state == PREPARING:
            return {"do": "prepare_target", "target": self.target, "media": self.snap["media"], "queue": self.snap.get("queue", [])}
        return None

    def prepared(self, now: float, source_position: float) -> dict:
        """Target ready: begin at the source's *current* source-time position (minus nothing, plus nothing)."""
        self.state = STARTING
        self.start_pos = max(0.0, float(source_position))
        self.start_wall = now
        self.actions.append("start_target")
        return {"do": "start_target", "target": self.target, "position": self.start_pos}

    def started(self, now: float) -> None:
        if self.state == STARTING:
            self.state = CONFIRMING
            self.t0 = now

    def target_status(self, playing: bool, position: float, now: float) -> dict | None:
        """Feed target polls. Returns the stop-source action only after confirmed PLAYING in tolerance."""
        if self.state != CONFIRMING:
            return None
        if playing and abs(position - self.expected_position(now)) <= MAX_DELTA_S + 3.0:
            self.state = DONE
            self.actions.append("stop_source")
            return {"do": "stop_source", "source": self.source}
        if now - self.t0 > CONFIRM_TIMEOUT_S:
            return self.fail(f"Couldn't start in {self.names[1]}; still playing in {self.names[0]}.")
        return None

    def expected_position(self, now: float) -> float:
        rate = float(self.snap.get("rate", 1.0))
        return self.start_pos + max(0.0, now - (self.start_wall or now)) * rate

    def tick(self, now: float) -> dict | None:
        if self.state in (STARTING, CONFIRMING) and now - self.t0 > CONFIRM_TIMEOUT_S * 2:
            return self.fail(f"Couldn't start in {self.names[1]}; still playing in {self.names[0]}.")
        return None

    def fail(self, message: str) -> dict:
        if self.state in (DONE, ROLLED_BACK):
            return {"do": "none"}
        self.state, self.message = ROLLED_BACK, message
        self.actions.append("abort_target")
        return {"do": "abort_target", "target": self.target, "keep_source": True, "message": message}

    def source_lost(self, target_playing: bool) -> dict | None:
        """Source died mid-handoff: carry on with the target if it is (or can be) playing."""
        if self.state in (DONE, ROLLED_BACK):
            return None
        if self.state == CONFIRMING and target_playing:
            self.state = DONE
            return {"do": "none", "message": f"Moved to {self.names[1]}."}
        return None

    @property
    def finished(self) -> bool:
        return self.state in (DONE, ROLLED_BACK)


class Mover:
    """Holds in-flight handoffs by id so a double tap is idempotent."""

    def __init__(self) -> None:
        self.active: dict[str, Handoff] = {}

    def begin(self, handoff_id: str, source: str, target: str, snapshot: dict, now: float, **names) -> tuple[Handoff | None, str]:
        if handoff_id in self.active:
            return self.active[handoff_id], "duplicate"
        if source == target:
            return None, "Already playing there."
        if any(h.target == target or h.source == source for h in self.active.values() if not h.finished):
            return None, "A move is already in progress."
        h = Handoff(handoff_id, source, target, snapshot, now, **names)
        self.active[handoff_id] = h
        return h, ""

    def reap(self, keep: int = 20) -> None:
        for k in [k for k, h in self.active.items() if h.finished][:-keep] if keep else []:
            del self.active[k]


def authorised(token_ok: bool, role: str) -> bool:
    """Automation endpoint: unauthenticated calls are rejected; only host/co-host may move rooms."""
    return bool(token_ok) and role in ("host", "cohost")
