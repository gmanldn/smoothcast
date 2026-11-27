import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import crossfade_plan as cp

A = {"id": "a", "kind": "music", "duration": 200.0}
B = {"id": "b", "kind": "music", "duration": 180.0}


def test_music_to_music_overlap_with_prewarm_before_start():
    p = cp.plan(A, B, enabled=True, seconds=5, queue_revision=7)
    assert p["mode"] == "crossfade" and p["fade_s"] == 5 and p["start_at"] == 195
    assert p["prewarm_at"] == 187 and p["next_id"] == "b"


def test_every_fallback_has_a_reason():
    for kw, cur, nxt in [({"enabled": False}, A, B), ({"enabled": True}, A, None),
                         ({"enabled": True}, A, {**B, "kind": "video"}),
                         ({"enabled": True}, A, {**B, "duration": None}),
                         ({"enabled": True, "receiver_ok": False}, A, B),
                         ({"enabled": True, "rate": 4}, A, B),
                         ({"enabled": True}, A, {**B, "duration": 1.5})]:
        p = cp.plan(cur, nxt, **kw)
        assert p["mode"] == "standard" and p["reason"], kw


def test_seconds_clamped_and_limited_by_short_tracks():
    assert cp.plan(A, B, enabled=True, seconds=99)["fade_s"] == cp.MAX_S
    assert cp.clamp_seconds("junk") == cp.SUGGESTED_S and cp.clamp_seconds(0) == cp.MIN_S
    assert cp.plan(A, {**B, "duration": 8}, enabled=True, seconds=12)["fade_s"] == 4.0


def test_invalidated_by_reorder_and_equal_power_gains():
    p = cp.plan(A, B, enabled=True, queue_revision=3)
    assert cp.still_valid(p, 3, "b") and not cp.still_valid(p, 4, "b") and not cp.still_valid(p, 3, "c")
    for t in (0, .25, .5, 1):
        o, i = cp.gains(t)
        assert math.isclose(o * o + i * i, 1.0)
    assert "acrossfade=d=5" in cp.filter_graph(5) and "alimiter" in cp.filter_graph(5)
