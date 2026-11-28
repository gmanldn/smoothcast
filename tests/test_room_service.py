import threading

import room_service as svc


def test_queue_and_playback_commands_share_one_snapshot():
    r = svc.RoomService()
    assert r.command({"kind": "add", "key": "k1", "item": "a", "title": "A"})["ok"]
    assert r.command({"kind": "claim", "key": "k2", "owner": "gui", "receiver": "tv"})["ok"]
    assert r.command({"kind": "play", "key": "k3", "owner": "gui", "item": "a"})["ok"]
    snap = r.snapshot()
    assert snap["queue"]["items"] == [{"item": "a", "title": "A"}]
    assert snap["playback"]["status"] == "playing" and snap["playback"]["owner"] == "gui"


def test_second_controller_cannot_take_a_held_receiver():
    r = svc.RoomService()
    r.command({"kind": "claim", "key": "k1", "owner": "gui", "receiver": "tv"})
    out = r.command({"kind": "claim", "key": "k2", "owner": "web", "receiver": "tv"})
    assert (out["ok"], out["reason"]) == (False, "receiver_busy")


def test_duplicate_key_is_idempotent_and_reported():
    r = svc.RoomService()
    first = r.command({"kind": "add", "key": "k", "item": "a"})
    again = r.command({"kind": "add", "key": "k", "item": "a"})
    assert first["ok"] and again["ok"] and again["duplicate"] and r.snapshot()["queue"]["revision"] == 1


def test_bad_payloads_are_rejected_without_raising():
    r = svc.RoomService()
    for bad in (None, [], {}, {"kind": 1, "key": "k"}, {"kind": "add"}, {"kind": "add", "key": "k", "item": 5},
                {"kind": "add", "key": "k", "item": "x" * 600}, {"kind": "move", "key": "k", "item": "a", "index": True},
                {"kind": "add", "key": "k", "base_revision": "0"}, {"kind": "explode", "key": "k"}):
        out = r.command(bad)
        assert out["ok"] is False and out["reason"] in ("bad_payload", "unknown_kind"), bad
    assert r.snapshot()["queue"]["revision"] == 0


def test_stale_base_revision_is_refused():
    r = svc.RoomService()
    r.command({"kind": "add", "key": "k1", "item": "a"})
    assert r.command({"kind": "add", "key": "k2", "item": "b", "base_revision": 0})["reason"] == "stale_revision"


def test_concurrent_adds_keep_a_gapless_log():
    r = svc.RoomService()
    threads = [threading.Thread(target=lambda n=n: r.command({"kind": "add", "key": f"k{n}", "item": f"i{n}"})) for n in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert r.snapshot()["queue"]["revision"] == 40 and len(r.snapshot()["queue"]["items"]) == 40
