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
import portal_uploads
from cast_portal_queue import portal_queue_id


PIN = "234567"


class RoomHarness:
    def __init__(self, count: int = 20,
                 uploads: portal_uploads.UploadManager | None = None) -> None:
        self.queue = [
            {"id": f"item-{index}", "title": f"track-{index}.mp3", "duration": 30}
            for index in range(count)
        ]
        self.calls: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.queue_revision = 0
        self.server = portal._PortalHTTPServer(
            ("127.0.0.1", 0), PIN, self.dispatch, uploads=uploads,
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
                return {"state": "PLAYING", "title": "Current film",
                        "queue_revision": self.queue_revision,
                        "queue": [dict(item) for item in self.queue]}
            if action in {"queue_remove", "queue_move", "queue_clear"}:
                if payload.get("queue_revision") != self.queue_revision:
                    raise portal.PortalRequestError(409, "Up Next changed; refresh before editing")
            if action == "queue_remove":
                self.queue[:] = [item for item in self.queue if item["id"] != payload["id"]]
                self.queue_revision += 1
                return "Removed from the queue."
            if action == "queue_move":
                item = next(item for item in self.queue if item["id"] == payload["id"])
                self.queue.remove(item)
                self.queue.insert(payload["position"], item)
                self.queue_revision += 1
                return "Queue order updated."
            if action == "queue_clear":
                self.queue.clear()
                self.queue_revision += 1
                return "Up Next cleared."
            if action == "queue_add":
                item_id = portal_queue_id(payload["path"])
                if all(item["id"] != item_id for item in self.queue):
                    self.queue.append({"id": item_id, "title": payload["name"], "duration": 0})
                    self.queue_revision += 1
                return "Added to the queue."
            return "accepted"

    def request(self, method: str, path: str, body: dict | bytes | None = None, *,
                cookie: str | None = None, csrf: str | None = None,
                content_type: str | None = None,
                extra_headers: dict[str, str] | None = None):
        headers = {"Host": self.host}
        if body is not None:
            if isinstance(body, dict):
                headers["Content-Type"] = "application/json"
                body = json.dumps(body).encode()
            elif content_type:
                headers["Content-Type"] = content_type
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if method in {"POST", "PUT"}:
            headers["Origin"] = self.origin
        headers.update(extra_headers or {})
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
        status, current, _headers = client.status()
        assert status == 200
        status, _body, _headers = client.action(
            {"action": "queue_move", "id": item_id, "position": 0,
             "queue_revision": current["state"]["queue_revision"],
             "queue_command_id": f"{client.participant_id}-move"},
        )
        assert status == 202
        status, current, _headers = client.status()
        assert status == 200
        status, _body, _headers = client.action({
            "action": "queue_remove", "id": item_id,
            "queue_revision": current["state"]["queue_revision"],
            "queue_command_id": f"{client.participant_id}-remove",
        })
        assert status == 202

    status, final, _headers = clients[0].status()
    assert status == 200
    assert [item["id"] for item in final["state"]["queue"]] == [
        f"item-{index}" for index in range(client_count, 20)
    ]
    assert sum(action == "queue_remove" for action, _payload in room.calls) == client_count


def test_guest_upload_is_queued_once_and_converges_across_room_clients(tmp_path):
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    room = RoomHarness(count=0, uploads=uploads)
    try:
        first, second = room.login("Phone 1"), room.login("Phone 2")
        status, created, _headers = room.request(
            "POST", "/api/uploads",
            {"name": "lan-movie.mkv", "size": 6, "queue": True},
            cookie=first.cookie, csrf=first.csrf,
        )
        assert status == 201
        upload_id = created["id"]
        status, progress, _headers = room.request(
            "PUT", f"/api/uploads/{upload_id}", b"abcdef",
            cookie=first.cookie, csrf=first.csrf,
            content_type="application/octet-stream",
            extra_headers={"Content-Range": "bytes 0-5/6"},
        )
        assert status == 200 and progress["ready_to_cast"] is False
        status, completed, _headers = room.request(
            "POST", f"/api/uploads/{upload_id}/complete", {"queue": True},
            cookie=first.cookie, csrf=first.csrf,
        )
        assert status == 202 and completed["message"] == "Added to the shared queue."
        uploaded_path = room.calls[-1][1]["path"]

        # Repeated finalization returns success without dispatching another queue add.
        status, _, _headers = room.request(
            "POST", f"/api/uploads/{upload_id}/complete", {"queue": True},
            cookie=first.cookie, csrf=first.csrf,
        )
        assert status == 202
        assert sum(action == "queue_add" for action, _payload in room.calls) == 1

        first_status, first_state, _headers = first.status()
        second_status, second_state, _headers = second.status()
        assert first_status == second_status == 200
        queue = first_state["state"]["queue"]
        assert queue == second_state["state"]["queue"]
        assert len(queue) == 1 and queue[0]["title"] == "lan-movie.mkv"
        assert first_state["state"]["title"] == "Current film"
        assert first_state["state"]["queue_revision"] == 1

        status, _result, _headers = second.action({
            "action": "queue_remove", "id": queue[0]["id"],
            "queue_revision": second_state["state"]["queue_revision"],
            "queue_command_id": f"{second.participant_id}-remove-upload",
        })
        assert status == 202
        status, cleared_state, _headers = first.status()
        assert status == 200 and cleared_state["state"]["queue"] == []
        assert cleared_state["state"]["title"] == "Current film"
        assert Path(uploaded_path).read_bytes() == b"abcdef"
        assert not any(action in {"cast_upload", "stop"} for action, _payload in room.calls)
    finally:
        room.close()
        uploads.close()


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
