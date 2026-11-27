"""Upload-panel view model (#570): speed/ETA smoothing, stage wording, resume invitation. Pure; clock injected."""
from __future__ import annotations

MIB = 1024 * 1024
ALPHA = 0.3
STAGES = {
    "negotiating": "Getting ready",
    "transferring": "Sending",
    "buffering": "Finishing up",
    "ready": "Ready to play",
    "playing": "Playing",
    "completed": "Done",
    "failed": "Didn't work",
    "cancelled": "Cancelled",
}


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v >= 0 else None


def fmt_bytes(n: float) -> str:
    return f"{n / MIB:.1f} MB" if n < 1024 * MIB else f"{n / (1024 * MIB):.2f} GB"


def eta_range(remaining: float, speed: float) -> str | None:
    """A range, never false precision. None when speed is unknown."""
    if remaining <= 0:
        return "a moment"
    if speed <= 0:
        return None
    lo, hi = remaining / (speed * 1.3), remaining / (speed * 0.7)
    if hi < 10:
        return "a few seconds"
    if hi < 90:
        return f"{int(lo // 5 * 5) or 5}–{int(-(-hi // 5) * 5)} seconds"
    return f"{max(1, int(lo // 60))}–{int(-(-hi // 60))} minutes"


class Meter:
    """EMA-smoothed throughput from (time, received_bytes) samples."""

    def __init__(self) -> None:
        self.last: tuple[float, float] | None = None
        self.speed = 0.0
        self.inst = 0.0

    def sample(self, now: float, received: float) -> None:
        if (n := _num(now)) is None or (r := _num(received)) is None:
            return
        if self.last and n > self.last[0] and r >= self.last[1]:
            self.inst = (r - self.last[1]) / (n - self.last[0])
            self.speed = self.inst if not self.speed else ALPHA * self.inst + (1 - ALPHA) * self.speed
        elif self.last and r < self.last[1]:                 # resumed from an earlier offset
            self.speed = self.inst = 0.0
        self.last = (n, r)


def route_text(source: str, node: str | None, dest: str | None, stored_on_node: bool) -> str:
    parts = [source] + ([node] if node and node != dest else []) + ([dest] if dest else [])
    where = "Stored on " + node if stored_on_node and node else "Still on your device"
    return " → ".join(parts) + f" · {where}"


def view(s: dict, meter: Meter, *, receiver_confirmed: bool = False, source: str = "This device", dest: str | None = None, file_available: bool = True) -> dict:
    """One row. 'Playing' is shown only when the receiver confirmed it."""
    state = s.get("state") if s.get("state") in STAGES else "failed"
    size, got = _num(s.get("size")) or 0.0, _num(s.get("received_bytes")) or 0.0
    got = min(got, size) if size else got
    if state == "playing" and not receiver_confirmed:
        state = "ready"
    pct = int(got * 100 // size) if size else 0
    active = state in ("negotiating", "transferring")
    eta = eta_range(size - got, meter.speed) if state == "transferring" else None
    label = STAGES[state]
    resume = None
    if state in ("negotiating", "transferring") and not file_available:
        state, label = "failed", "Paused"
        resume = "Choose the same file again to carry on from where it stopped."
    detail = f"{fmt_bytes(got)} of {fmt_bytes(size)}" if size else ""
    if active and meter.speed:
        detail += f" · {meter.speed / MIB:.1f} MB/s" + (f" · about {eta} left" if eta else "")
    node = (s.get("target") or {}).get("node")
    return {"state": state, "label": label, "percent": pct, "detail": detail, "route": route_text(source, node, dest, (_num(s.get("durable_bytes")) or 0) > 0),
            "aria": f"{s.get('name', 'File')}: {label}, {pct} percent", "can_pause": active and resume is None, "can_cancel": state not in ("completed", "cancelled", "failed") or resume is not None,
            "resume": resume, "error": s.get("error")}


def same_file(orig: dict, picked: dict) -> bool:
    """Manual reselect after reload: name+size(+lastModified when both known) must match."""
    if orig.get("name") != picked.get("name") or orig.get("size") != picked.get("size"):
        return False
    a, b = orig.get("last_modified"), picked.get("last_modified")
    return a is None or b is None or a == b


def cast_confirm(media: str, target: str | None, eligible: list[str]) -> dict:
    """Guided journey: never silently change or start; suggest an eligible target."""
    if target and (target in eligible):
        return {"ask": f"Cast {media} to {target}?", "suggest": target, "can_confirm": True}
    if eligible:
        return {"ask": f"Where should {media} play?", "suggest": eligible[0], "can_confirm": False}
    return {"ask": "No screen or speaker is ready. You can still add it to Up Next.", "suggest": None, "can_confirm": False}
