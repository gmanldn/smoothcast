"""Energy-aware node choice (#428). Pure scoring; no power measurement.

Node record: ``on_battery`` (bool), ``cpu_load_1m`` (rounded), ``user_active`` (bool). Missing metrics mean
awake + idle. ``choose`` picks, among options that meet the quality need, the lowest (energy, latency, id).
``keep_stream`` encodes the rule that an active stream is never moved only to save energy.
"""
from __future__ import annotations

BATTERY_PENALTY, ACTIVE_PENALTY, ASLEEP_PENALTY = 50, 20, 100
LOAD_STEP = 10                                           # points per 1.0 of 1-min load, capped
LOAD_CAP = 40


def fields(on_battery=None, cpu_load_1m=None, user_active=None) -> dict:
    """What a node publishes. Unknown stays absent so receivers can treat it as idle."""
    out: dict = {}
    if isinstance(on_battery, bool):
        out["on_battery"] = on_battery
    if isinstance(cpu_load_1m, (int, float)) and not isinstance(cpu_load_1m, bool) and cpu_load_1m >= 0:
        out["cpu_load_1m"] = round(float(cpu_load_1m), 1)
    if isinstance(user_active, bool):
        out["user_active"] = user_active
    return out


def score(node: dict) -> int:
    """Lower is better."""
    s = 0
    if node.get("awake") is False:
        s += ASLEEP_PENALTY
    if node.get("on_battery") is True:
        s += BATTERY_PENALTY
    if node.get("user_active") is True:
        s += ACTIVE_PENALTY
    load = node.get("cpu_load_1m")
    if isinstance(load, (int, float)) and not isinstance(load, bool) and load > 0:
        s += min(LOAD_CAP, int(load * LOAD_STEP))
    return s


def choose(options: list[dict], meets=lambda o: True) -> dict | None:
    ok = [o for o in options if meets(o)]
    return min(ok, key=lambda o: (score(o), o.get("latency_ms", 0), o["id"]), default=None)


def keep_stream(current: dict | None, best: dict | None, active: bool) -> dict | None:
    """A stream already running stays where it is; energy only decides NEW placements."""
    if active and current is not None:
        return current
    return best
