"""Web clients in the mesh: summaries, guest-tier feed and SSE route (#402)."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_clients as mcl
import mesh_model as mm
import mesh_sim as sim
import mesh_state as st
import portal
import portal_mesh_http

ME, A, B = "1" * 32, "a" * 32, "b" * 32


def rec(node, rev=1, **kw):
    return mm.NodeRecord(node_id=node, boot_id="c" * 32, name=f"N-{node[:2]}", rev=rev,
                         version="1.2.0", **kw)


def tv(i):
    return mm.TargetObservation(f"tv-{i}", "cast", f"TV {i}")


class Rig:
    """A publisher over MeshState driven on a virtual clock."""

    def __init__(self):
        self.clock = sim.SimClock()
        self.state = st.MeshState(rec(ME), clock=self.clock)
        self.alive = {A, B}
        self.pub = st.ViewPublisher(clock=self.clock, state=self.state,
                                    is_alive=lambda n: n in self.alive)
        self.feed = mcl.MeshFeed(self.pub, generation="g1")

    def put(self, record):
        self.state.accept(record, current_boot=record.boot_id)
        self.pub.changed()
        self.clock.advance(0.2)


# -- summaries -----------------------------------------------------------------

def test_client_summaries_hide_raw_ids_skip_offline_and_clean_names():
    people = [{"id": "secret-participant-id", "name": " Sam\x00 ", "online": True},
              {"id": "gone", "name": "Away", "online": False}, "junk", None]
    screens = [{"id": "ab12", "name": "TV", "ready": True, "video": True, "state": "playing"},
               {"id": "cd34", "name": "Kitchen", "ready": True, "video": False, "state": "idle"},
               {"id": "ef56", "name": "Dead", "ready": False}]
    out = mcl.client_summaries(people, screens)
    assert {(c.role, c.name) for c in out} == {("controller", "Sam"), ("screen", "TV"),
                                                ("speaker", "Kitchen")}
    assert all(c.id[0] in "ps" and "secret" not in c.id and "ab12" not in c.id for c in out)
    assert [c.flags for c in out if c.name == "TV"] == [("playing",)]
    assert mcl.client_summaries(people, screens) == out          # stable ids
    many = [{"id": str(i), "name": "n", "online": True} for i in range(200)]
    assert len(mcl.client_summaries(many, [])) == mm.MAX_CLIENTS


def test_screen_targets_reflect_readiness_and_skip_bad_ids():
    out = mcl.screen_targets([
        {"id": "aa11", "name": "TV", "ready": True, "video": True, "state": "idle"},
        {"id": "bb22", "name": "Spk", "ready": True, "video": False, "state": "playing"},
        {"id": "cc33", "name": "Old", "ready": False},
        {"id": "../x", "name": "Evil", "ready": True}, 7])
    by = {t.id: t for t in out}
    assert by["screen-aa11"].state == "ready" and "video/mp4" in by["screen-aa11"].formats
    assert by["screen-bb22"].state == "busy" and by["screen-bb22"].formats == ("audio/mpeg",)
    assert by["screen-cc33"].state == "stale" and len(out) == 3
    assert all(t.kind == "screen" for t in out)


# -- feed --------------------------------------------------------------------------

def frames_text(frames):
    return b"".join(frames).decode()


def data_of(frame):
    line = [ln for ln in frame.decode().split("\n") if ln.startswith("data: ")][0]
    return json.loads(line[6:])


def test_new_stream_gets_a_snapshot_then_ordered_deltas():
    r = Rig()
    stream = r.feed.open("k1")
    first = stream.poll()
    assert len(first) == 1 and data_of(first[0])["type"] == "snapshot"
    r.put(rec(A, targets=(tv(1),)))
    r.put(rec(A, 2, targets=(tv(1), tv(2))))
    frames = stream.poll()
    assert [data_of(f)["type"] for f in frames] == ["delta", "delta"]
    ids = [f.decode().split("\n")[0] for f in frames]
    assert ids == ["id: g1:1", "id: g1:2"] and stream.poll() == []


def test_resume_with_last_event_id_replays_only_missed_events():
    r = Rig()
    r.put(rec(A))
    r.put(rec(A, 2, targets=(tv(1),)))
    r.put(rec(A, 3, targets=(tv(1), tv(2))))
    resumed = r.feed.open("k", "g1:1")
    assert [f.decode().split("\n")[0] for f in resumed.poll()] == ["id: g1:2", "id: g1:3"]
    current = r.feed.open("k", "g1:3")
    assert current.poll() == []


@pytest.mark.parametrize("last", ["g1:999", "old:2", "garbage", "", None, "g1:-4", "g1:x"])
def test_unknown_future_or_foreign_ids_fall_back_to_a_snapshot(last):
    r = Rig()
    r.put(rec(A))
    frames = r.feed.open("k", last).poll()
    assert len(frames) == 1 and data_of(frames[0])["type"] == "snapshot"


def test_history_gap_forces_a_snapshot_and_memory_stays_bounded():
    r = Rig()
    r.feed = mcl.MeshFeed(r.pub, generation="g1", history=8)
    slow = r.feed.open("slow")
    slow.poll()
    for i in range(300):
        r.put(rec(A, i + 1, targets=(tv(i % 5),)))
    assert len(r.feed._ring) <= 8
    frames = slow.poll()
    assert len(frames) == 1 and data_of(frames[0])["type"] == "snapshot"
    assert data_of(frames[0])["nodes"][1]["node_id"] == A
    old = r.feed.open("late", "g1:3")                       # id fell out of the ring
    assert data_of(old.poll()[0])["type"] == "snapshot"


def test_each_change_is_encoded_once_and_shared_by_all_streams():
    r = Rig()
    streams = [r.feed.open(f"k{i}") for i in range(5)]
    for s in streams:
        s.poll()
    r.put(rec(A, targets=(tv(1),)))
    polled = [s.poll() for s in streams]
    assert all(p[0] is polled[0][0] for p in polled)


def test_stream_caps_close_and_revocation():
    r = Rig()
    keys = [r.feed.open("same") for _ in range(mcl.MAX_STREAMS_PER_KEY)]
    with pytest.raises(mcl.FeedFull):
        r.feed.open("same")
    small = mcl.MeshFeed(r.pub, max_streams=2)
    small.open("a")
    small.open("b")
    with pytest.raises(mcl.FeedFull):
        small.open("c")
    assert r.feed.close_keys({"same"}) == 3 and r.feed.stream_count == 0
    assert all(s.closed and s.poll() == [] for s in keys)
    r.feed.open("same")
    r.feed.close()
    assert r.feed.stream_count == 0


def test_guest_payloads_never_contain_other_nodes_private_data():
    r = Rig()
    r.put(rec(A, addresses=("10.88.77.66",),
              clients=(mm.ClientSummary("cl1", "screen", name="Secret-Sam"),),
              sources=(mm.SourceSummary("audio", 5, ("audio/secret",)),),
              edges=(mm.EdgeObservation("target", "tv-9", 5, 5),),
              targets=(tv(1),)))
    text = frames_text(r.feed.open("k").poll()) + frames_text(
        r.feed.open("k2", "g1:0").poll())
    snapshot = json.dumps(mcl.guest_snapshot(r.pub.view))
    for blob in (text, snapshot):
        for secret in ("Secret-Sam", "10.88.77.66", "audio/secret", "cl1"):
            assert secret not in blob
    assert "TV 1" in snapshot and '"client_count":1' in snapshot.replace(" ", "")


def test_blocked_consumers_wake_on_new_frames_and_time_out_otherwise():
    r = Rig()
    stream = r.feed.open("k")
    stream.poll()
    assert stream.wait(0.05) is False
    result = []
    t = threading.Thread(target=lambda: result.append(stream.wait(3.0)))
    t.start()
    time.sleep(0.05)
    r.put(rec(A))
    t.join(3)
    assert result == [True]
    stream.close()
    assert stream.wait(0.01) is False


# -- HTTP ----------------------------------------------------------------------------

PIN = "234567"


class Http:
    def __init__(self, feed=None):
        self.server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN,
                                               lambda a, p: {"queue": []})
        self.server.mesh_feed = feed
        self.port = self.server.server_address[1]
        self.t = threading.Thread(target=self.server.serve_forever,
                                  kwargs={"poll_interval": 0.02}, daemon=True)
        self.t.start()

    def login(self):
        c = HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/login", json.dumps({"pin": PIN, "name": "Sam"}),
                  {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
                   "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        c.close()
        return r.getheader("Set-Cookie").split(";")[0]

    def open(self, path, cookie=None, headers=None, host=None):
        c = HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie:
            h["Cookie"] = cookie
        h.update(headers or {})
        c.request("GET", path, headers=h)
        return c, c.getresponse()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def read_frame(resp):
    lines = []
    while True:
        line = resp.fp.readline().decode()
        if not line:
            return None
        if line == "\n":
            if lines:
                return "".join(lines)
            continue
        lines.append(line)


@pytest.fixture
def http_rig():
    r = Rig()
    h = Http(r.feed)
    yield r, h
    h.close()


def test_routes_require_auth_a_running_mesh_and_a_valid_host():
    plain = Http(None)
    try:
        for path in ("/api/mesh", "/api/mesh/events"):
            c, resp = plain.open(path)
            assert resp.status == 401
            c.close()
        cookie = plain.login()
        c, resp = plain.open("/api/mesh", cookie)
        assert resp.status == 503
        c.close()
        c, resp = plain.open("/api/mesh", cookie, host="evil.example")
        assert resp.status == 400
        c.close()
    finally:
        plain.close()


def test_snapshot_route_returns_the_guest_view(http_rig):
    r, h = http_rig
    r.put(rec(A, targets=(tv(1),)))
    c, resp = h.open("/api/mesh", h.login())
    body = json.loads(resp.read())
    c.close()
    assert resp.status == 200 and body["event"] == "g1:1"
    assert {n["node_id"] for n in body["mesh"]["nodes"]} == {ME, A}


def test_sse_streams_snapshot_then_live_deltas_and_resumes(http_rig):
    r, h = http_rig
    cookie = h.login()
    c, resp = h.open("/api/mesh/events", cookie)
    assert resp.status == 200 and "text/event-stream" in resp.getheader("Content-Type")
    first = read_frame(resp)
    assert "event: mesh" in first and '"type":"snapshot"' in first
    r.put(rec(A, targets=(tv(7),)))
    delta = read_frame(resp)
    assert '"type":"delta"' in delta and "id: g1:1" in delta and "TV 7" in delta
    c.close()
    r.put(rec(A, 2, targets=(tv(7), tv(8))))
    c2, resp2 = h.open("/api/mesh/events", cookie, {"Last-Event-ID": "g1:1"})
    missed = read_frame(resp2)
    assert "id: g1:2" in missed and "TV 8" in missed
    c2.close()


def test_stream_cap_and_revocation_close_connections(http_rig):
    r, h = http_rig
    cookie = h.login()
    conns = []
    for _ in range(mcl.MAX_STREAMS_PER_KEY):
        c, resp = h.open("/api/mesh/events", cookie)
        assert resp.status == 200
        read_frame(resp)
        conns.append((c, resp))
    c, resp = h.open("/api/mesh/events", cookie)
    assert resp.status == 429
    c.close()
    token = cookie.split("=", 1)[1]
    participant = h.server.session_participant(token)
    assert h.server.revoke_participant(participant) == 1
    for c, resp in conns:
        assert read_frame(resp) is None            # server closed the stream
        c.close()
    assert r.feed.stream_count == 0
    c, resp = h.open("/api/mesh/events", cookie)
    assert resp.status == 401
    c.close()


def test_keepalive_comments_flow_when_idle(http_rig, monkeypatch):
    r, h = http_rig
    monkeypatch.setattr(portal_mesh_http, "KEEPALIVE_S", 0.1)
    c, resp = h.open("/api/mesh/events", h.login())
    read_frame(resp)
    line = resp.fp.readline().decode()
    assert line.startswith(": keepalive")
    c.close()
