import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import speaker_presets as sp

ROOMS = {"k": {"name": "Kitchen", "receiver": "rk"}, "g": {"name": "Garden", "receiver": "rg"}, "l": {"name": "Lounge", "receiver": "rl"}}


def test_save_validates_clamps_and_limits():
    p, pid = sp.save([], "Dinner party", [{"room": "k", "volume": 40}, {"room": "g", "volume": 250}, {"room": "l", "volume": None}], 1)
    assert pid and [e["volume"] for e in p[0]["entries"]] == [40, 100, None]
    assert sp.save(p, "dinner PARTY", [{"room": "k", "volume": 1}], 2) == (p, None)     # duplicate name
    assert sp.save(p, "", [{"room": "k", "volume": 1}], 2)[1] is None and sp.save(p, "x", [], 2)[1] is None
    q, same = sp.save(p, "Dinner", [{"room": "k", "volume": 5}], 3, preset_id=pid)
    assert same == pid and len(q) == 1 and q[0]["name"] == "Dinner"
    full = []
    for i in range(sp.MAX_PRESETS):
        full, _ = sp.save(full, f"p{i}", [{"room": "k", "volume": 1}], i)
    assert sp.save(full, "one more", [{"room": "k", "volume": 1}], 99)[1] is None


def test_recall_skips_offline_names_them_and_leaves_leave_alone():
    p = sp.save([], "Dinner party", [{"room": "k", "volume": 40}, {"room": "g", "volume": 30}, {"room": "l", "volume": None}], 1)[0][0]
    r = sp.plan_recall(p, ROOMS, {"rk": True, "rg": False, "rl": True})
    assert r["ok"] and r["group"] == ["rk", "rl"] and r["volumes"] == {"rk": 0.4}
    assert r["toast"] == "Dinner party on · Garden skipped (speaker offline)"
    assert not sp.plan_recall(p, ROOMS, {})["ok"]


def test_ceiling_overrides_preset_volume_and_guest_gate():
    p = sp.save([], "Loud", [{"room": "k", "volume": 90}], 1)[0][0]
    assert sp.plan_recall(p, ROOMS, {"rk": True}, ceilings={"rk": 0.6})["volumes"] == {"rk": 0.6}
    g = sp.plan_recall(p, ROOMS, {"rk": True}, guest=True)
    assert not g["ok"] and "guests" in g["reason"] and g["group"] == []
    assert sp.plan_recall(p, ROOMS, {"rk": True}, guest=True, guests_allowed=True)["ok"]


def test_prune_drops_deleted_rooms_marks_edited_and_removes_empty():
    ps = sp.save([], "A", [{"room": "k", "volume": 1}, {"room": "zz", "volume": 2}], 1)[0]
    ps = sp.save(ps, "B", [{"room": "zz", "volume": 2}], 1)[0]
    out = sp.prune(ps, {"k"})
    assert [p["name"] for p in out] == ["A"] and out[0]["edited"] and len(out[0]["entries"]) == 1
    assert sp.prune([{"id": "x", "name": "C", "entries": [{"room": "k", "volume": 1}], "edited": False}], {"k"})[0]["edited"] is False
