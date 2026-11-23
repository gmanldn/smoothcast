"""Room SSE endpoint (#316 slice 1): initial state, change-only pushes, caps, auth, shutdown."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_status

PIN = "234567"


class Rig:
    def __init__(self):
        self.published = portal_status.PublishedStatus()
        self.state = {"title": "Film A", "state": "PLAYING", "position": 1.0, "duration": 100.0,
                      "queue": [{"id": "q1", "title": "Song 1"}], "active": True, "busy": False,
                      "revision": 1, "session_id": "s1", "queue_revision": 0}
        self.published.publish(self.state)
        self.server = portal._PortalHTTPServer(
            ("127.0.0.1", 0), PIN, lambda *_: "ok", status_snapshot=self.published.read)
        self.server.status_peek = self.published.peek
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def update(self, **changes):
        self.state = {**self.state, **changes}
        self.published.publish(self.state)

    def login(self, name):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("POST", "/api/login", json.dumps({"pin": PIN, "name": name}),
                     {"Host": self.host, "Origin": f"http://{self.host}", "Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie").split(";")[0]
        conn.close()
        return cookie

    def stream(self, cookie, path="/api/events", *, last_event_id=None):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        resume = f"Last-Event-ID: {last_event_id}\r\n" if last_event_id is not None else ""
        sock.sendall(f"GET {path} HTTP/1.1\r\nHost: {self.host}\r\nCookie: {cookie}\r\n{resume}\r\n".encode())
        return Stream(sock)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Stream:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""
        head = self._until(b"\r\n\r\n")
        self.status = int(head.split(b" ", 2)[1])
        self.headers = head.decode().lower()

    def _until(self, marker, timeout=2.0):
        deadline = time.monotonic() + timeout
        while marker not in self.buffer:
            if time.monotonic() > deadline:
                raise TimeoutError(self.buffer)
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise TimeoutError(self.buffer) from None
            if not chunk:
                raise EOFError
            self.buffer += chunk
        head, _, self.buffer = self.buffer.partition(marker)
        return head

    def event(self, timeout=2.0):
        raw = self._until(b"\n\n", timeout).decode()
        fields = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line and not line.startswith(":"))
        return raw, fields

    def silent_for(self, seconds):
        try:
            self._until(b"\n\n", seconds)
        except TimeoutError:
            return True
        return False

    def close(self):
        self.sock.close()


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(portal, "EVENT_POLL_SECONDS", 0.03)
    monkeypatch.setattr(portal, "EVENT_PING_SECONDS", 60.0)
    monkeypatch.setattr(portal, "EVENT_RESEND_SECONDS", 60.0)
    value = Rig()
    yield value
    value.close()


def test_first_event_is_the_full_status_document(rig):
    stream = rig.stream(rig.login("Sam"))
    assert stream.status == 200 and "text/event-stream" in stream.headers and "no-store" in stream.headers
    _raw, fields = stream.event()
    assert fields["event"] == "state"
    document = json.loads(fields["data"])
    assert fields["id"] == f'{document["stream_epoch"]}:1'
    assert document["ok"] is True and document["state"]["title"] == "Film A"
    assert document["state"]["room"]["me"]["name"] == "Sam"
    stream.close()


def test_pushes_only_changes_and_ignores_the_moving_playhead(rig):
    stream = rig.stream(rig.login("Sam"))
    stream.event()
    rig.update(position=50.0)
    assert stream.silent_for(0.4), "position-only changes must not be pushed"
    rig.update(title="Film B")
    _raw, fields = stream.event()
    assert fields["id"].endswith(":2") and json.loads(fields["data"])["state"]["title"] == "Film B"
    rig.update(queue=[{"id": "q1", "title": "Song 1"}, {"id": "q2", "title": "Song 2"}])
    _raw, fields = stream.event()
    assert fields["id"].endswith(":3") and len(json.loads(fields["data"])["state"]["queue"]) == 2
    assert stream.silent_for(0.3)
    stream.close()


def test_room_activity_is_pushed(rig):
    sam = rig.login("Sam")
    stream = rig.stream(sam)
    stream.event()
    rig.server.room.record("someone", "action", {"action": "stop"})
    _raw, fields = stream.event()
    assert json.loads(fields["data"])["state"]["room"]["activity"][-1]["data"]["action"] == "stop"
    stream.close()


def test_idle_stream_gets_keepalive_pings(rig, monkeypatch):
    monkeypatch.setattr(portal, "EVENT_PING_SECONDS", 0.1)
    stream = rig.stream(rig.login("Sam"))
    stream.event()
    raw, _fields = stream.event(timeout=2.0)
    assert raw.startswith(": ping")
    stream.close()


def test_unauthenticated_request_is_refused(rig):
    stream = rig.stream("sc_portal_session=nope")
    assert stream.status == 401
    stream.close()


def test_per_participant_cap_and_slot_release(rig, monkeypatch):
    monkeypatch.setattr(portal, "EVENT_PING_SECONDS", 0.05)
    cookie = rig.login("Sam")
    streams = [rig.stream(cookie) for _ in range(portal.EVENT_STREAMS_PER_PARTICIPANT)]
    assert all(s.status == 200 for s in streams)
    refused = rig.stream(cookie)
    assert refused.status == 429 and "retry-after" in refused.headers
    refused.close()
    for s in streams:
        s.close()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:  # the server notices on its next write (ping)
        again = rig.stream(cookie)
        if again.status == 200:
            again.close()
            return
        again.close()
        time.sleep(0.1)
    pytest.fail("slots were not released after the clients disconnected")


def test_total_cap_spans_participants(rig, monkeypatch):
    monkeypatch.setattr(portal, "EVENT_STREAMS_TOTAL", 2)
    first, second, third = rig.login("Ana"), rig.login("Bo"), rig.login("Cy")
    kept = [rig.stream(first), rig.stream(second)]
    assert [s.status for s in kept] == [200, 200]
    over = rig.stream(third)
    assert over.status == 429
    for s in (*kept, over):
        s.close()


def test_server_close_ends_open_streams(rig):
    stream = rig.stream(rig.login("Sam"))
    stream.event()
    rig.server.stopping.set()
    with pytest.raises((EOFError, ConnectionError)):
        stream._until(b"never-appears", timeout=2.0)
    stream.close()

def test_reconnect_replays_history_then_converges_on_fresh_snapshot(rig):
    cookie = rig.login("Sam")
    first = rig.stream(cookie)
    _, initial = first.event()
    rig.update(title="Film B")
    _, changed = first.event()
    first.close()
    rig.update(title="Film C")
    resumed = rig.stream(cookie, last_event_id=initial["id"])
    _, replayed = resumed.event()
    _, fresh = resumed.event()
    assert replayed["id"] == changed["id"]
    assert json.loads(replayed["data"])["state"]["title"] == "Film B"
    assert json.loads(fresh["data"])["state"]["title"] == "Film C"
    assert int(fresh["id"].split(":")[1]) > int(replayed["id"].split(":")[1])
    resumed.close()


def test_missing_history_and_restarted_epoch_get_current_state(rig):
    cookie = rig.login("Sam")
    first = rig.stream(cookie)
    _, initial = first.event()
    first.close()
    epoch = json.loads(initial["data"])["stream_epoch"]
    rig.update(title="Recovered film")
    missing = rig.stream(cookie, last_event_id=f"{epoch}:999999")
    _, gap = missing.event()
    assert json.loads(gap["data"])["stream_resync"] == "gap"
    assert json.loads(gap["data"])["state"]["title"] == "Recovered film"
    missing.close()
    restarted = rig.stream(cookie, last_event_id="0000000000000000:4")
    _, event = restarted.event()
    assert json.loads(event["data"])["stream_resync"] == "restarted"
    assert json.loads(event["data"])["stream_epoch"] == epoch
    restarted.close()


def test_replay_never_crosses_participants_and_revocation_clears_events(rig):
    sam = rig.login("Sam")
    first = rig.stream(sam)
    _, initial = first.event()
    first.close()
    lee = rig.login("Lee")
    foreign = rig.stream(lee, last_event_id=initial["id"])
    _, event = foreign.event()
    assert json.loads(event["data"])["stream_resync"] == "gap"
    assert json.loads(event["data"])["state"]["room"]["me"]["name"] == "Lee"
    foreign.close()
    owner = rig.server.session_participant(sam.split("=", 1)[1])
    assert owner is not None
    rig.server.revoke_participant(owner)
    refused = rig.stream(sam, last_event_id=initial["id"])
    assert refused.status == 401
    refused.close()


def test_two_clients_converge_across_play_pause_seek_loss_and_queue_edits(rig):
    """A published owner-state change reaches every connected participant.

    Different participants have different stream IDs and room.me metadata,
    but must agree on the authoritative media, queue and source-time state.
    """
    ana, bo = rig.login("Ana"), rig.login("Bo")
    clients = [rig.stream(ana), rig.stream(bo)]
    try:
        assert all(s.status == 200 for s in clients)
        first = [json.loads(s.event()[1]["data"])["state"] for s in clients]
        assert all(state["revision"] == 1 for state in first)

        changes = [
            dict(state="PAUSED", revision=2),
            dict(state="PLAYING", position=43.5, revision=3),
            dict(state="OFFLINE", receiver=None, revision=4),
            dict(state="PLAYING", revision=5, queue_revision=1,
                 queue=[{"id": "q2", "title": "Song 2"}, {"id": "q1", "title": "Song 1"}]),
        ]
        for change in changes:
            rig.update(**change)
            current = [json.loads(s.event()[1]["data"])["state"] for s in clients]
            for state in current:
                for key in ("state", "revision", "position", "session_id",
                            "queue_revision", "queue", "receiver"):
                    assert state.get(key) == rig.state.get(key), (key, change)
            assert current[0]["revision"] == current[1]["revision"]
            assert current[0]["queue_revision"] == current[1]["queue_revision"]
    finally:
        for stream in clients:
            stream.close()


def test_late_subscriber_receives_current_full_snapshot(rig):
    rig.update(title="New Film", state="PAUSED", position=73.25, revision=18,
               queue_revision=2, queue=[{"id": "q9", "title": "Latest"}])
    stream = rig.stream(rig.login("Later"))
    try:
        assert stream.status == 200
        document = json.loads(stream.event()[1]["data"])
        state = document["state"]
        assert (state["title"], state["state"], state["position"]) == (
            "New Film", "PAUSED", 73.25)
        assert (state["revision"], state["queue_revision"]) == (18, 2)
        assert state["queue"] == [{"id": "q9", "title": "Latest"}]
        assert state["room"]["me"]["name"] == "Later"
    finally:
        stream.close()


def test_revoking_a_participant_closes_an_already_open_stream(rig):
    cookie = rig.login("Sam")
    stream = rig.stream(cookie)
    try:
        assert stream.status == 200
        stream.event()
        owner = rig.server.session_participant(cookie.split("=", 1)[1])
        assert owner is not None
        rig.server.revoke_participant(owner)
        with pytest.raises((EOFError, ConnectionError)):
            stream._until(b"this-event-does-not-exist", timeout=2.0)
        refused = rig.stream(cookie)
        try:
            assert refused.status == 401
        finally:
            refused.close()
    finally:
        stream.close()


def test_twenty_simultaneous_clients_include_one_nonreading_browser(rig):
    """One slow browser cannot prevent the other 19 from receiving updates."""
    sessions = [rig.login(f"Guest {index}") for index in range(20)]
    streams = [rig.stream(cookie) for cookie in sessions]
    try:
        assert all(s.status == 200 for s in streams)
        # Stream 0 deliberately does not read its initial frame.
        for stream in streams[1:]:
            assert json.loads(stream.event()[1]["data"])["state"]["revision"] == 1
        rig.update(state="PAUSED", revision=2)
        for stream in streams[1:]:
            state = json.loads(stream.event(timeout=3.0)[1]["data"])["state"]
            assert state["state"] == "PAUSED" and state["revision"] == 2
    finally:
        for stream in streams:
            stream.close()
