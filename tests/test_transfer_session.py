import itertools

import pytest

from src import transfer_session as T

PEERS = [{"id": "a", "online": True, "load": 0.5}, {"id": "b", "online": True, "load": 0.1}, {"id": "off", "online": False}]


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def tr():
    c = Clock()
    n = itertools.count(1)
    x = T.Transfers(c, rng=lambda: f"{next(n):032x}")
    x.c = c
    return x


def body(**kw):
    d = {"intent": "queue", "client_op_id": "op1", "name": "../a/Movie.mkv", "size": 100, "media_type": "video/x-matroska"}
    d.update(kw)
    return d


def test_create_sanitises_name_picks_least_loaded_and_hides_paths(tr):
    st, v = tr.create("o", body(), PEERS)
    assert st == 201 and v["name"] == "Movie.mkv" and v["target"]["node"] == "b" and v["state"] == "negotiating"
    assert v["upload"] == f"/api/transfers/{v['id']}/data" and "/home" not in str(v)


@pytest.mark.parametrize("intent", ["add", "play", "queue"])
def test_intents_accepted(tr, intent):
    assert tr.create("o", body(intent=intent), PEERS)[0] == 201


def test_copy_needs_target_and_honours_it(tr):
    assert tr.create("o", body(intent="copy"), PEERS)[1]["error"] == "target_required"
    st, v = tr.create("o", body(intent="copy", target={"node": "a"}), PEERS)
    assert st == 201 and v["target"]["node"] == "a"


def test_duplicate_post_is_idempotent_and_reuse_conflicts(tr):
    a = tr.create("o", body(), PEERS)[1]
    st, b = tr.create("o", body(), PEERS)
    assert st == 200 and b["id"] == a["id"]
    st, e = tr.create("o", body(size=5), PEERS)
    assert (st, e["error"]) == (409, "op_reused")


def test_unknown_offline_and_no_peers(tr):
    assert tr.create("o", body(target={"node": "zz"}), PEERS)[:2] == (404, {"error": "unknown_target", "message": "That computer isn't part of this home."})
    st, e = tr.create("o", body(client_op_id="x", target={"node": "off"}), PEERS)
    assert (st, e["error"]) == (409, "target_offline")
    assert tr.create("o", body(client_op_id="y"), [PEERS[2]])[1]["error"] == "target_offline"


@pytest.mark.parametrize("bad,code,status", [({"intent": "zap"}, "bad_request", 400), ({"size": 0}, "bad_size", 400), ({"size": True}, "bad_size", 400),
                                             ({"size": T.MAX_FILE + 1}, "too_large", 413), ({"name": "///"}, "bad_request", 400), ({"digest": "xyz"}, "bad_request", 400),
                                             ({"client_op_id": ""}, "bad_request", 400)])
def test_malformed_bounds(tr, bad, code, status):
    st, e = tr.create("o", body(**bad), PEERS)
    assert (st, e["error"]) == (status, code)


def test_quotas(tr):
    for i in range(T.MAX_PER_OWNER):
        assert tr.create("o", body(client_op_id=f"k{i}"), PEERS)[0] == 201
    assert tr.create("o", body(client_op_id="more"), PEERS)[1]["error"] == "too_many_transfers"
    t2 = T.Transfers(Clock())
    assert t2.create("o", body(size=T.MAX_FILE), PEERS)[0] == 201
    assert t2.create("p", body(size=T.MAX_FILE), PEERS)[0] == 201
    assert t2.create("q", body(size=T.MAX_FILE), PEERS)[1]["error"] == "no_space"


def test_owner_isolation_looks_like_not_found(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    for call in (tr.get, tr.cancel, tr.resume, tr.finalise):
        assert call("intruder", tid)[0] == 404
    assert tr.put_chunk("intruder", tid, 0, 1)[0] == 404


def test_sequential_chunks_offset_mismatch_and_bounds(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    st, v = tr.put_chunk("o", tid, 0, 40)
    assert st == 200 and v["state"] == "transferring" and v["received_bytes"] == 40
    st, e = tr.put_chunk("o", tid, 0, 40)
    assert (st, e["error"], e["received_bytes"]) == (409, "offset_mismatch", 40)
    assert tr.put_chunk("o", tid, 40, 61)[0] == 416
    assert tr.put_chunk("o", tid, 40, 0)[0] == 400
    assert tr.put_chunk("o", tid, 40, T.CHUNK + 1)[0] == 413
    assert tr.put_chunk("o", tid, 40, 60)[1]["state"] == "buffering"


def test_resume_restarts_at_durable_bytes(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    tr.put_chunk("o", tid, 0, 60)
    tr.mark_durable(tid, 30)
    st, v = tr.resume("o", tid)
    assert v["received_bytes"] == 30 and v["durable_bytes"] == 30
    assert tr.put_chunk("o", tid, 30, 70)[1]["state"] == "buffering"


def test_finalise_incomplete_digest_and_idempotent_retry(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    tr.put_chunk("o", tid, 0, 50)
    assert tr.finalise("o", tid)[1]["error"] == "incomplete"
    tr.put_chunk("o", tid, 50, 50)
    assert tr.finalise("o", tid)[1]["state"] == "ready"
    assert tr.finalise("o", tid)[0] == 200                      # retry racing finish
    assert tr.advance(tid, "playing") and tr.advance(tid, "completed") and not tr.advance(tid, "playing")
    d = "a" * 64
    t2 = tr.create("o", body(client_op_id="d", digest=d), PEERS)[1]["id"]
    tr.put_chunk("o", t2, 0, 100)
    st, e = tr.finalise("o", t2, "b" * 64)
    assert (st, e["error"]) == (422, "digest_mismatch") and tr.get("o", t2)[1]["state"] == "failed"
    assert tr.put_chunk("o", t2, 100, 1)[0] == 409


def test_cancel_then_chunk_and_double_cancel(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    assert tr.cancel("o", tid)[0] == 204 and tr.cancel("o", tid)[0] == 204
    assert tr.put_chunk("o", tid, 0, 1)[1]["error"] == "not_accepting"
    t2 = tr.create("o", body(client_op_id="z"), PEERS)[1]["id"]
    tr.put_chunk("o", t2, 0, 100)
    tr.finalise("o", t2)
    tr.advance(t2, "playing"); tr.advance(t2, "completed")
    assert tr.cancel("o", t2)[1]["error"] == "already_finished"


def test_expiry_returns_410(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    tr.c.t += T.IDLE_TTL_S + 1
    st, e = tr.get("o", tid)
    assert (st, e["error"]) == (410, "expired")


def test_stale_source_fails(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]
    st, e = tr.source_changed("o", tid)
    assert (st, e["error"]) == (409, "source_changed") and tr.get("o", tid)[1]["error"] == "source_changed"


def test_target_lost_reroutes_without_reupload_when_durable(tr):
    tid = tr.create("o", body(), PEERS)[1]["id"]            # target b
    tr.put_chunk("o", tid, 0, 50)
    tr.mark_durable(tid, 50)
    assert tr.target_lost("b", PEERS) == [(tid, "rerouted:a")]
    v = tr.get("o", tid)[1]
    assert v["target"]["node"] == "a" and v["route"] == "relay" and v["state"] == "transferring"


def test_target_lost_fails_without_durable_copy_or_for_copy_intent(tr):
    t1 = tr.create("o", body(), PEERS)[1]["id"]
    tr.put_chunk("o", t1, 0, 50)                             # not durable
    t2 = tr.create("o", body(client_op_id="c", intent="copy", target={"node": "b"}), PEERS)[1]["id"]
    out = dict(tr.target_lost("b", PEERS))
    assert out == {t1: "failed", t2: "failed"} and tr.get("o", t1)[1]["error"] == "target_lost"


def test_guard_lan_and_cross_origin():
    assert T.guard("h:1", None, True) is None and T.guard("h:1", "http://h:1", True) is None
    assert T.guard("h:1", "http://evil.example", True)[1]["error"] == "cross_origin"
    assert T.guard("h:1", None, False)[0] == 403
