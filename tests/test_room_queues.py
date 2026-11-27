import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import room_queues as rq


def it(k): return {"content_key": k, "title": k}


def test_solo_and_house_queues_isolated_by_revision_and_content():
    r = rq.RoomQueues(); r.add("house", it("h1")); r.go_solo("kids", "Kids' room")
    hrev = r.rev["house"]
    assert r.add("kids", it("s1")) == {"ok": True, "queue": "kids", "revision": 1} and r.add("kids", it("s2"))["revision"] == 2
    r.remove("kids", "s1")
    assert r.rev["house"] == hrev and [i["content_key"] for i in r.q["house"]] == ["h1"] and [i["content_key"] for i in r.q["kids"]] == ["s2"]
    r.add(None, it("h2")); assert r.rev["kids"] == 3 and len(r.q["kids"]) == 1
    assert r.add("nope", it("x")) == {"ok": False, "error": "That room isn't available."}


def test_view_header_and_default_queue_is_house():
    r = rq.RoomQueues(); r.add(None, it("h1")); r.go_solo("kids", "Kids' room")
    v = r.view("kids"); assert v["header"] == "Kids' room (solo)" and v["queue"] == "kids" and v["items"] == []
    v = r.view("lounge"); assert v["header"] == "House queue" and v["queue"] == "house" and v["items"] == [it("h1")] and v["revision"] == 1
    assert rq.header("house") == "House queue" and rq.header("solo") == "This room (solo)"


def test_go_solo_copies_nothing_by_default_and_take_current_is_opt_in():
    r = rq.RoomQueues(); r.add(None, it("h1")); r.go_solo("a"); assert r.q["a"] == [] and r.rev["a"] == 0
    r.go_solo("b", take_current=it("now")); assert r.q["b"] == [it("now")] and r.rev["b"] == 1
    assert r.go_solo("../x" * 30)["ok"] is False and r.go_solo("house")["ok"] is False


def test_rejoin_requires_confirmation_then_appends_with_dedupe():
    r = rq.RoomQueues(); r.add(None, it("a")); r.go_solo("k"); r.add("k", it("a")); r.add("k", it("b")); r.add("k", it("c"))
    assert r.rejoin("k", False) == {"ok": False, "needs_confirmation": True, "message": "Add 3 items to the House queue?"} and "k" in r.q
    out = r.rejoin("k", True); assert out == {"ok": True, "appended": 2, "revision": 2, "queue": "house"}
    assert [i["content_key"] for i in r.q["house"]] == ["a", "b", "c"] and "k" not in r.q and r.view("k")["queue"] == "house"
    assert r.rejoin("k", True) == {"ok": True, "appended": 0}


def test_room_deleted_while_solo_folds_into_house_and_shared_room_is_one_queue():
    r = rq.RoomQueues(); r.go_solo("k"); r.add("k", it("x")); r.add("k", it("y"))
    assert r.room_deleted("k")["appended"] == 2 and [i["content_key"] for i in r.q["house"]] == ["x", "y"] and "k" not in r.mode
    assert r.room_deleted("ghost") == {"ok": True, "appended": 0} and r.room_deleted("house") == {"ok": True, "appended": 0}
    r.go_solo("k2"); a = r.add("k2", it("p")); b = r.add("k2", it("q"), revision=a["revision"])      # two phones, same queue
    assert b["ok"] and r.view("k2")["items"] == [it("p"), it("q")]
    assert r.add("k2", it("z"), revision=0) == {"ok": False, "error": "The queue changed — refresh and try again.", "stale": True, "revision": 2}


def test_bad_items_and_caps():
    r = rq.RoomQueues(); assert r.add(None, {"title": "x"})["ok"] is False and r.add(None, {"content_key": 5})["ok"] is False
    for i in range(rq.MAX_ITEMS): r.add(None, it(f"k{i}"))
    assert r.add(None, it("over")) == {"ok": False, "error": "The queue is full."}
