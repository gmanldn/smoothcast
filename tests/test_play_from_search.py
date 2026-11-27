import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import play_from_search as pfs

KEY = "qh:abcdef123456"


def item(*origins):
    return pfs.make_item(KEY, "Film", 5400, list(origins))


def fake(table, calls):
    def probe(o, k):
        calls.append(o)
        r = table[o]
        if isinstance(r, Exception):
            raise r
        return r
    return probe


def test_key_validation_rejects_paths_and_junk():
    for bad in ("/etc/passwd", "../x", "C:\\a\\b", "short", "a" * 200, None, 5, "qh:/home/sam/x.mkv"):
        assert not pfs.valid_key(bad) and pfs.make_item(bad, "t", 1, []) is None
    assert pfs.valid_key(KEY)


def test_local_copy_wins_without_any_network_probe():
    calls = []; r = pfs.Resolver(lambda: 0).resolve(item({"id": "lounge", "online": True}, {"id": "me", "local": True}), fake({}, calls))
    assert r == {"ok": True, "origin": "me", "local": True, "size": None, "tried": []} and calls == []


def test_failed_revalidation_falls_through_to_next_origin_in_order():
    calls = []; t = {"a": (404, {}), "b": (409, {"error": "changed"}), "c": (200, {"ok": True, "size": 99})}
    it = item({"id": "a", "online": True, "wired": True}, {"id": "b", "online": True, "rtt": 1}, {"id": "c", "online": True, "rtt": 9}, {"id": "off", "online": False})
    r = pfs.Resolver(lambda: 0).resolve(it, fake(t, calls))
    assert r["ok"] and r["origin"] == "c" and r["size"] == 99 and calls == ["a", "b", "c"]
    assert r["tried"] == [{"origin": "a", "why": "gone"}, {"origin": "b", "why": "changed"}]


def test_timeouts_and_exceptions_fall_through_and_all_failed_gives_plain_error():
    calls = []; t = {"a": (504, {}), "b": RuntimeError("boom")}
    r = pfs.Resolver(lambda: 0).resolve(item({"id": "a", "online": True}, {"id": "b", "online": True}), fake(t, calls))
    assert r == {"ok": False, "error": "This isn't available right now — its computer may be asleep.", "tried": [{"origin": "a", "why": "timeout"}, {"origin": "b", "why": "error"}]}
    assert pfs.Resolver(lambda: 0).resolve(item({"id": "z", "online": False}), fake({}, []))["ok"] is False


def test_negative_cache_skips_recent_failure_then_retries_after_ttl():
    now = [0.0]; res = pfs.Resolver(lambda: now[0]); calls = []; t = {"a": (404, {}), "b": (200, {"ok": True, "size": 1})}
    it = item({"id": "a", "online": True, "wired": True}, {"id": "b", "online": True})
    res.resolve(it, fake(t, calls)); res.resolve(it, fake(t, calls)); assert calls == ["a", "b", "b"]
    now[0] = pfs.NEG_CACHE_S + 1; res.resolve(it, fake(t, calls)); assert calls[-2:] == ["a", "b"]


def test_enqueue_idempotent_and_revision_checked():
    c = pfs.Commands(); it = item({"id": "a", "online": True})
    r1 = c.enqueue("cmd1", 0, it); assert r1 == {"ok": True, "revision": 1, "position": 0}
    assert c.enqueue("cmd1", 0, it) == {**r1, "duplicate": True} and len(c.queue) == 1
    stale = c.enqueue("cmd2", 0, it); assert stale["stale"] and stale["revision"] == 1 and len(c.queue) == 1
    assert c.enqueue("cmd3", 1, it)["position"] == 1 and c.enqueue("cmd4", 2, None)["ok"] is False
    for i in range(600): c.enqueue(f"x{i}", c.revision, it)
    assert len(c.done) <= 500


def test_no_absolute_paths_in_client_visible_queue_state():
    it = pfs.make_item(KEY, "Film", 1, [{"id": "/home/sam/movies", "online": True}, {"id": "lounge", "online": True, "path": "/home/sam/Movies/f.mkv"}])
    c = pfs.Commands(); c.enqueue("c", 0, it)
    blob = json.dumps(c.client_view())
    assert "/home" not in blob and "path" not in blob and "sam" not in blob and "lounge" in blob and len(it.origins) == 1
