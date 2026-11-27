import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import rooms_zones as rz


def mk(tmp_path):
    r = rz.Rooms(tmp_path / "rooms.json")
    a = r.add("Lounge", "sofa", 1); b = r.add("Kitchen", "kitchen", 1)
    return r, a, b


def test_crud_persists_and_receiver_lives_in_one_room(tmp_path):
    r, a, b = mk(tmp_path)
    r.assign(a, "tv", 2); r.assign(a, "bar", 2); r.set_default(a, "video", "tv", 3)
    r.assign(b, "tv", 4)                                        # moves, clearing the old default
    again = rz.Rooms(tmp_path / "rooms.json")
    assert again.rooms[a]["receivers"] == ["bar"] and again.rooms[b]["receivers"] == ["tv"]
    assert again.rooms[a]["default_video"] is None
    assert not r.set_default(a, "video", "tv", 5) and r.add("lounge", "tv", 6) is None and r.add("  ", "tv", 6) is None
    assert r.rooms[r.add("X", "bogus-icon", 7)]["icon"] == "tv"


def test_merge_newest_wins_and_tombstones():
    a, b = rz.Rooms(), rz.Rooms()
    rid = a.add("Lounge", "sofa", 1)
    b.merge(a.state()); assert rid in b.rooms
    a.rename(rid, "Living room", 5)
    b.merge(a.state()); assert b.rooms[rid]["name"] == "Living room"
    b.rename(rid, "Old edit", 3); b.merge(a.state()); assert b.rooms[rid]["name"] == "Living room"   # older loses
    a.delete(rid, 9)
    b.merge(a.state()); assert rid not in b.rooms
    stale = {"rooms": [{**a.rooms.get(rid, {"id": rid, "name": "Ghost", "icon": "tv", "receivers": [], "updated_at": 4})}], "tombstones": {}}
    stale["rooms"][0]["updated_at"] = 4
    assert b.merge(stale) == 0 and rid not in b.rooms           # resurrection blocked
    newer = {"rooms": [{"id": rid, "name": "Back", "icon": "tv", "receivers": [], "updated_at": 12}], "tombstones": {}}
    assert b.merge(newer) == 1 and b.rooms[rid]["name"] == "Back"


def test_merge_ignores_garbage_and_dedupes_receivers():
    a = rz.Rooms()
    assert a.merge({"rooms": [{"nope": 1}], "tombstones": {"x": "bad"}}) == 0
    a.merge({"rooms": [{"id": "r1", "name": "A", "icon": "tv", "receivers": ["d"], "updated_at": 1},
                       {"id": "r2", "name": "B", "icon": "tv", "receivers": ["d"], "updated_at": 2}]})
    assert sum("d" in r["receivers"] for r in a.rooms.values()) == 1 and a.rooms["r2"]["receivers"] == ["d"]


def test_picker_rooms_first_subtitle_and_unassigned_prompt(tmp_path):
    r, a, b = mk(tmp_path)
    r.assign(a, "tv", 2); r.assign(a, "bar", 2)
    devs = [{"id": "tv", "name": "TV", "online": True}, {"id": "bar", "name": "Soundbar", "online": True},
            {"id": "mini", "name": "Google-Home-Mini-4F2A", "online": False}]
    p = r.picker(devs)
    lounge = next(x for x in p["rooms"] if x["name"] == "Lounge")
    assert lounge["subtitle"] == "TV + Soundbar · on" and [d["id"] for d in p["other"]] == ["mini"]
    assert next(x for x in p["rooms"] if x["name"] == "Kitchen")["subtitle"] == "No devices"
    assert [d["id"] for d in r.unassigned(devs, set())] == ["mini"] and r.unassigned(devs, {"mini"}) == []
