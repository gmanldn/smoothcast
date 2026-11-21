"""Deterministic multi-client conformance over the real portal HTTP boundary.

These tests use only a loopback listener and a fake dispatch target. They model
independently authenticated browser clients without GTK, sleeps, or receivers.
"""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


PIN = "234567"


class RoomHarness:
    def __init__(self, count: int = 20) -> None:
        self.queue = [
            {"id": f"item-{index}", "title": f"track-{index}.mp3", "duration": 30}
            for index in range(count)
        ]
        self.calls: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.server = portal._PortalHTTPServer(
            ("127.0.0.1", 0), PIN, self.dispatch,
        )
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.origin = f"http://{self.host}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True,
        )
        self.thread.start()

    def dispatch(self, action: str, payload: dict) -> dict | str:
        with self.lock:
            self.calls.append((action, dict(payload)))
            if action == "status":
                return {"state": "PLAYING", "queue": [dict(item) for item in self.queue]}
            if action == "queue_remove":
                self.queue[:] = [item for item in self.queue if item["id"] != payload["id"]]
                return "Removed from the queue."
            if action == "queue_move":
                item = next(item for item in self.queue if item["id"] == payload["id"])
                self.queue.remove(item)
                self.queue.insert(payload["position"], item)
                return "Queue order updated."
            return "accepted"

    def request(self, method: str, path: str, body: dict | None = None, *,
                cookie: str | None = None, csrf: str | None = None):
        headers = {"Host": self.host}
        if body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if method == "POST":
            headers["Origin"] = self.origin
        conn = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else {}, dict(response.getheaders())
        finally:
            conn.close()

    def login(self, name: str) -> "RoomClient":
        status, result, headers = self.request("POST", "/api/login", {"pin": PIN, "name": name})
        assert status == 200
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        return RoomClient(self, cookie, result["csrf"], result["participant"]["id"])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


class RoomClient:
    def __init__(self, harness: RoomHarness, cookie: str, csrf: str, participant_id: str) -> None:
        self.harness = harness
        self.cookie = cookie
        self.csrf = csrf
        self.participant_id = participant_id

    def status(self):
        return self.harness.request("GET", "/api/status", cookie=self.cookie)

    def action(self, body: dict):
        return self.harness.request(
            "POST", "/api/action", body, cookie=self.cookie, csrf=self.csrf,
        )


@pytest.fixture
def room():
    harness = RoomHarness()
    yield harness
    harness.close()


@pytest.mark.parametrize("client_count", [2, 5, 20])
def test_authenticated_clients_converge_and_all_can_edit_shared_queue(room, client_count):
    clients = [room.login(f"Guest {index}") for index in range(client_count)]

    snapshots = [client.status() for client in clients]
    assert all(status == 200 for status, _body, _headers in snapshots)
    room_views = [body["state"]["room"] for _status, body, _headers in snapshots]
    assert all(len(view["participants"]) == client_count for view in room_views)
    assert all({person["id"] for person in view["participants"]}
               == {client.participant_id for client in clients} for view in room_views)

    for index, client in enumerate(clients):
        item_id = f"item-{index}"
        status, _body, _headers = client.action(
            {"action": "queue_move", "id": item_id, "position": 0,
             "queue_revision": 0,
             "queue_command_id": f"{client.participant_id}-move"},
        )
        assert status == 202
        status, _body, _headers = client.action({
            "action": "queue_remove", "id": item_id, "queue_revision": 0,
            "queue_command_id": f"{client.participant_id}-remove",
        })
        assert status == 202

    status, final, _headers = clients[0].status()
    assert status == 200
    assert [item["id"] for item in final["state"]["queue"]] == [
        f"item-{index}" for index in range(client_count, 20)
    ]
    assert sum(action == "queue_remove" for action, _payload in room.calls) == client_count


def test_simultaneous_seeks_are_serialized_and_one_stale_generation_is_rejected(room):
    first, second = room.login("Phone 1"), room.login("Phone 2")
    first.status()
    session_id, revision, _owner = room.server.fence.snapshot()
    barrier = threading.Barrier(2)
    results: list[int] = []

    def seek(client: RoomClient, value: int, command_id: str) -> None:
        barrier.wait()
        status, _body, _headers = client.action({
            "client_id": command_id,
            "command_id": command_id,
            "expected_session_id": session_id,
            "expected_revision": revision,
            "action": "seek",
            "payload": {"value": value},
        })
        results.append(status)

    threads = [
        threading.Thread(target=seek, args=(first, 10, "seek-one")),
        threading.Thread(target=seek, args=(second, 20, "seek-two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()

    assert sorted(results) == [202, 409]
    assert sum(action == "seek" for action, _payload in room.calls) == 1
