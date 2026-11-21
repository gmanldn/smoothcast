"""LAN dashboard HTTP behavior using only a private loopback test listener."""
from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import sys
import threading
import json
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


PIN = "234567"


class PortalRig:
    def __init__(self, uploads=None, clock=None, queue=None):
        self.calls = []
        self.queue = list(queue or [])

        def dispatch(action, payload):
            self.calls.append((action, payload))
            if action == "status":
                return {"title": "sample.mp4", "state": "PLAYING", "queue": self.queue}
            return "accepted"

        self.server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, dispatch,
                                                uploads=uploads, clock=clock or time.monotonic)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def request(self, method, path, body=None, *, cookie=None, csrf=None, origin=None, host=None,
                content_type=None, extra_headers=None):
        headers = {"Host": host or self.host}
        if origin is not None:
            headers["Origin"] = origin
        if cookie:
            headers["Cookie"] = cookie
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if body is not None:
            if isinstance(body, dict):
                headers["Content-Type"] = "application/json"
                body = json.dumps(body).encode()
            elif content_type:
                headers["Content-Type"] = content_type
        headers.update(extra_headers or {})
        conn = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


@pytest.fixture
def rig():
    value = PortalRig()
    yield value
    value.close()


def decode(body):
    import json
    return json.loads(body)


def test_pin_is_six_securely_selected_digits():
    assert len(portal.new_pin()) == portal.PIN_LENGTH
    assert set(portal.new_pin()).issubset(set(portal.PIN_DIGITS))
    choices = iter("123456")
    assert portal.new_pin(choice=lambda _alphabet: next(choices)) == "123456"


def test_friendly_name_is_short_lowercase_and_stable():
    assert portal.friendly_name("Living-Room Laptop") == "smoothcast-living-room-laptop"
    assert portal.friendly_name("smoothcast") == "smoothcast"
    assert portal.friendly_name("  --  ") == "smoothcast"
    assert portal.friendly_name("A" * 80) == "smoothcast-" + "a" * 21
    assert portal.valid_friendly_name("smoothcast-lounge")
    assert not portal.valid_friendly_name("SmoothCast")
    assert not portal.valid_friendly_name("bad name")
    assert not portal.valid_friendly_name("")


def test_portal_rejects_non_rfc1918_addresses():
    for address in ("0.0.0.0", "127.0.0.1", "169.254.1.2", "203.0.113.10", "8.8.8.8"):
        with pytest.raises(portal.PortalError):
            portal.Portal(address, lambda *_args: {})


def test_dashboard_html_is_local_and_contains_no_pin_or_status_data(rig):
    status, body, headers = rig.request("GET", "/")
    assert status == 200
    page = body.decode()
    assert "fetch(\"/api/status\"" in page
    assert "https://" not in page and "http://" not in page
    assert PIN not in page
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "setTimeout(()=>controller.abort(),60000)" in page
    assert 'if(activeUploadController)activeUploadController.abort()' in page
    assert "Select Resume upload to retry" in page
    assert "Audio is validated and added to the shared queue" in page
    assert "video can be queued or streamed" in page
    assert 'accept="audio/*,video/*,.mkv,.ts,.wmv" multiple' in page
    assert "while(batchIndex<batchFiles.length" in page
    assert "six-digit PIN" in page
    assert 'inputmode="numeric"' in page
    assert 'pattern="[0-9]{6}"' in page
    assert page.index('div id="dashboard" hidden') < page.index('id="networkActivity"')
    assert 'title.textContent=item.title' in page
    assert 'detail.textContent=' in page
    assert 'id="musicAutogain"' in page
    assert 'id="name"' in page and 'id="people"' in page and 'id="activity"' in page
    assert 'id="peers"' in page and "renderPeers(s.peers" in page
    assert ".slice(0,6)" in page
    assert "queue_vote" in page and "queue_play" in page
    assert 'id="clearQueue"' in page and "act(\"queue_clear\")" in page
    assert "queue_revision=queueRevision" in page and "body.queue_command_id=`q" in page
    assert "Add to the shared queue" in page


def test_status_requires_a_pin_and_rejects_host_rebinding(rig):
    status, body, _ = rig.request("GET", "/api/status")
    assert status == 401 and decode(body)["ok"] is False
    status, _, _ = rig.request("GET", "/api/status", host="evil.example")
    assert status == 400
    assert rig.calls == []


def login(rig, pin=PIN, name="Guest"):
    status, body, headers = rig.request("POST", "/api/login", {"pin": pin, "name": name},
                                        origin=f"http://{rig.host}")
    return status, decode(body), headers.get("Set-Cookie", "").split(";", 1)[0]


def test_revocation_cancels_private_guest_upload_without_touching_playback(tmp_path):
    import portal_uploads
    manager = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads=manager)
    try:
        _, participant, cookie = login(rig, PIN, "Uploader")
        token = cookie.partition("=")[2]
        created = manager.create(token, "example.mp4", 1024)
        upload_id = created["id"]
        path = manager.root / f"{upload_id}.partial"
        assert path.exists()
        assert rig.server.revoke_participant(participant["participant"]["id"]) == 1
        assert not path.exists()
        assert manager.snapshot() == []
        status, _body, _headers = rig.request(
            "POST", "/api/uploads", {"name": "next.mp4", "size": 1024},
            cookie=cookie, csrf=participant["csrf"], origin=f"http://{rig.host}")
        assert status == 403
        assert all(name not in {"stop", "seek", "queue_remove"} for name, _ in rig.calls)
    finally:
        rig.close()
        manager.close()


def test_desktop_wires_host_only_revoke_and_confirmed_end_access():
    from gui_source import main_window_methods
    methods = main_window_methods()
    assert "portal_guest_dropdown" in methods["_build_portal_card"]
    assert "portal_end_access_button" in methods["_build_portal_card"]
    assert "revoke_guest" in methods["_portal_revoke_selected"]
    assert "Adw.MessageDialog" in methods["_portal_confirm_end_access"]
    assert "current.end_guest_access()" in methods["_portal_end_guest_access"]


def test_host_can_revoke_one_guest_without_stopping_playback_or_others(rig):
    status, first, cookie_a = login(rig, PIN, "Alice")
    assert status == 200
    status, second, cookie_b = login(rig, PIN, "Bob")
    assert status == 200
    participant = first["participant"]["id"]
    assert rig.server.revoke_participant(participant) == 1
    assert rig.server.revoke_participant(participant) == 0
    assert rig.request("GET", "/api/status", cookie=cookie_a)[0] == 401
    assert rig.request("GET", "/api/status", cookie=cookie_b)[0] == 200
    status, _data, _headers = rig.request(
        "POST", "/api/action", {"action": "seek", "value": 30},
        cookie=cookie_a, csrf=first["csrf"], origin=f"http://{rig.host}")
    assert status == 403
    assert all(name not in {"seek", "stop"} for name, _ in rig.calls)
    assert {p["name"] for p in rig.server.room.snapshot()["participants"]} == {"Bob"}
    assert second["participant"]["id"] in rig.server.room.participants


def test_host_rotates_pin_and_signs_out_all_without_touching_receiver(rig):
    _, alice, cookie_a = login(rig, PIN, "Alice")
    _, bob, cookie_b = login(rig, PIN, "Bob")
    old_fence = rig.server.fence.snapshot()
    new_access_pin = rig.server.revoke_all()
    assert new_access_pin.isdigit() and len(new_access_pin) == portal.PIN_LENGTH
    assert new_access_pin != PIN
    assert rig.server.fence.snapshot()[:2] != old_fence[:2]
    assert rig.request("GET", "/api/status", cookie=cookie_a)[0] == 401
    assert rig.request("GET", "/api/status", cookie=cookie_b)[0] == 401
    assert login(rig, PIN, "Old PIN")[0] == 401
    status, guest, cookie_c = login(rig, new_access_pin, "New Guest")
    assert status == 200 and guest["participant"]["name"] == "New Guest"
    assert rig.request("GET", "/api/status", cookie=cookie_c)[0] == 200
    assert len(rig.server.room.snapshot()["participants"]) == 1
    assert all(name not in {"seek", "stop", "next", "previous"} for name, _ in rig.calls)
    assert alice["participant"]["id"] != bob["participant"]["id"]


def test_authorised_guest_payloads_are_fenced_at_gtk_dispatch_boundary(rig):
    _, guest, cookie = login(rig, PIN)
    key = rig.server._session_key(cookie.partition("=")[2])
    assert rig.server.session_key_active(key)
    rig.server.revoke_all()
    assert not rig.server.session_key_active(key)
    status, _body, _headers = rig.request(
        "POST", "/api/action", {"action": "next"},
        cookie=cookie, csrf=guest["csrf"], origin=f"http://{rig.host}")
    assert status == 403
    from gui_source import main_window_methods
    source = main_window_methods()["_portal_handle"]
    assert "session_key_active(session_key)" in source
    assert '"_portal_auth_key"' in source


def test_public_http_has_no_guest_revocation_or_pin_rotation_api(rig):
    _status, guest, cookie = login(rig, PIN)
    for path in ("/api/revoke", "/api/rotate-pin", "/api/revoke-all"):
        status, _body, _headers = rig.request(
            "POST", path, {}, cookie=cookie, csrf=guest["csrf"],
            origin=f"http://{rig.host}")
        assert status == 404


def test_login_is_serialised_with_host_rotation(rig, monkeypatch):
    # A concurrent PIN rotation cannot intervene after the PIN check but
    # before the cookie is entered in the session table.
    entered = threading.Event()
    proceed = threading.Event()
    original = rig.server.create_session
    def delayed_create(name):
        entered.set()
        assert proceed.wait(2)
        return original(name)
    monkeypatch.setattr(rig.server, "create_session", delayed_create)
    login_result = {}
    def run_login():
        login_result["value"] = login(rig, PIN, "Alice")
    thread = threading.Thread(target=run_login)
    thread.start()
    assert entered.wait(2)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(rig.server.revoke_all)
        assert not future.done()
        proceed.set()
        thread.join(3)
        new_access_pin = future.result(timeout=3)
    assert login_result["value"][0] == 200
    _status, _body, old_cookie = login_result["value"]
    assert rig.request("GET", "/api/status", cookie=old_cookie)[0] == 401
    assert login(rig, new_access_pin)[0] == 200


def test_pin_login_sets_http_only_session_and_dashboard_reads_main_state(rig):
    status, raw, headers = rig.request("POST", "/api/login", {"pin": PIN},
                                      origin=f"http://{rig.host}")
    result = decode(raw)
    set_cookie = headers.get("Set-Cookie", "")
    cookie = set_cookie.split(";", 1)[0]
    assert status == 200 and result["ok"]
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    status, body, headers = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200 and decode(body)["state"]["title"] == "sample.mp4"
    assert headers["Cache-Control"] == "no-store"
    assert rig.calls == [("status", {})]


def test_authenticated_status_exposes_only_the_peer_directory_snapshot(rig):
    _, _result, cookie = login(rig)
    rig.server.peer_directory = SimpleNamespace(snapshot=lambda: [{
        "id": "a" * 32, "name": "smoothcast-lounge", "version": 1,
        "compatible": True, "capabilities": ["room"],
        "url": "http://192.168.1.25:8765/",
    }])
    status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200
    state = decode(body)["state"]
    assert state["peer_discovery_available"] is True
    assert state["peers"][0]["name"] == "smoothcast-lounge"
    assert state["peers"][0]["url"] == "http://192.168.1.25:8765/"
    assert state["peers"][0]["compatible"] is True


def test_named_sessions_share_presence_and_votes(rig):
    first_status, first, cookie = login(rig, PIN, "Sam")
    assert first_status == 200 and first["participant"]["name"] == "Sam"
    second_status, second, _ = login(rig, PIN, "Sam")
    assert second_status == 200
    assert second["participant"]["name"] == "Sam (2)"
    status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200
    room = decode(body)["state"]["room"]
    assert {person["name"] for person in room["participants"]} == {"Sam", "Sam (2)"}
    assert room["me"]["name"] == "Sam"


def test_profile_edit_only_changes_the_authenticated_participant(rig):
    _, first, cookie = login(rig, PIN, "Sam")
    _, second, other_cookie = login(rig, PIN, "Alex")
    origin = f"http://{rig.host}"
    hostile = '<img src=x onerror="alert(1)">'
    status, body, _ = rig.request(
        "POST", "/api/profile",
        {"name": hostile, "participant_id": second["participant"]["id"], "role": "host"},
        cookie=cookie, csrf=first["csrf"], origin=origin,
    )
    assert status == 200 and decode(body)["participant"]["name"] == hostile
    status, body, _ = rig.request("GET", "/api/status", cookie=other_cookie)
    assert status == 200
    people = {person["id"]: person["name"]
              for person in decode(body)["state"]["room"]["participants"]}
    assert people == {first["participant"]["id"]: hostile,
                      second["participant"]["id"]: "Alex"}
    assert "textContent=person.name" in portal._HTML
    assert "innerHTML" not in portal._HTML


def test_queue_votes_are_per_person_and_require_a_live_item():
    queue = [{"id": "abc123", "title": "film.mkv", "duration": 90}]
    rig = PortalRig(queue=queue)
    try:
        _, first, cookie = login(rig, PIN)
        origin = f"http://{rig.host}"
        status, body, _ = rig.request("POST", "/api/action",
                                      {"action": "queue_vote", "id": "abc123", "value": True},
                                      cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 404  # queue has not been observed yet
        rig.request("GET", "/api/status", cookie=cookie)
        status, body, _ = rig.request("POST", "/api/action",
                                      {"action": "queue_vote", "id": "abc123", "value": True},
                                      cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 202
        status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
        item = decode(body)["state"]["queue"][0]
        assert item["votes"] == 1 and item["voted"] is True
        status, _, _ = rig.request("POST", "/api/action",
                                   {"action": "queue_vote", "id": "missing", "value": True},
                                   cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 404
    finally:
        rig.close()


def test_queue_actions_are_forwarded_to_the_gui(rig):
    rig.queue = [{"id": "one", "title": "one.mkv", "duration": 0}]
    _, result, cookie = login(rig)
    rig.request("GET", "/api/status", cookie=cookie)
    origin = f"http://{rig.host}"
    for index, (action, extra) in enumerate((
            ("next", {}), ("previous", {}),
            ("queue_play", {"id": "one"}),
            ("queue_remove", {"id": "one"}),
            ("queue_move", {"id": "one", "position": 0}),
            ("queue_clear", {}))):
        payload = {"action": action, **extra}
        if action in {"queue_remove", "queue_move", "queue_clear"}:
            payload.update(queue_command_id=f"test-{index}", queue_revision=0)
        status, body, _ = rig.request("POST", "/api/action", payload, cookie=cookie,
                                      csrf=result["csrf"], origin=origin)
        assert status == 202, (action, body)


def test_queue_command_id_replays_and_rejects_altered_payload(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    command = {"action": "queue_clear", "queue_revision": 0,
               "queue_command_id": "clear-once"}

    first_status, first_body, _ = rig.request(
        "POST", "/api/action", command, cookie=cookie,
        csrf=result["csrf"], origin=origin)
    replay_status, replay_body, _ = rig.request(
        "POST", "/api/action", command, cookie=cookie,
        csrf=result["csrf"], origin=origin)
    altered_status, _, _ = rig.request(
        "POST", "/api/action", {**command, "queue_revision": 1}, cookie=cookie,
        csrf=result["csrf"], origin=origin)

    assert first_status == replay_status == 202
    assert decode(first_body) == decode(replay_body)
    assert altered_status == 409
    assert [action for action, _ in rig.calls].count("queue_clear") == 1


def test_bad_pin_is_rate_limited_per_client(rig):
    for _ in range(portal.MAX_ATTEMPTS):
        assert login(rig, "Z")[0] == 401
    assert login(rig)[0] == 401


def test_actions_require_same_origin_session_and_csrf(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    status, _, _ = rig.request("POST", "/api/action", {"action": "stop"},
                               cookie=cookie, origin=origin)
    assert status == 403
    status, _, _ = rig.request("POST", "/api/action", {"action": "stop"},
                               cookie=cookie, csrf=result["csrf"], origin="http://evil.example")
    assert status == 403
    status, body, _ = rig.request("POST", "/api/action", {"action": "stop"},
                                  cookie=cookie, csrf=result["csrf"], origin=origin)
    assert status == 202 and decode(body)["ok"]
    assert rig.calls == [("stop", {"action": "stop"})]


def test_phone_autogain_toggle_is_authenticated_and_requires_a_boolean(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    status, _, _ = rig.request(
        "POST", "/api/action", {"action": "music_autogain", "value": "true"},
        cookie=cookie, csrf=result["csrf"], origin=origin,
    )
    assert status == 400
    assert rig.calls == []
    status, body, _ = rig.request(
        "POST", "/api/action", {"action": "music_autogain", "value": True},
        cookie=cookie, csrf=result["csrf"], origin=origin,
    )
    assert status == 202 and decode(body)["ok"]
    assert rig.calls == [("music_autogain", {"action": "music_autogain", "value": True})]


@pytest.mark.parametrize("payload", [
    {"action": "cast", "file": "/etc/passwd"},
    {"action": ["stop"]},
    {"action": "seek", "value": float("nan")},
    {"action": "seek", "value": -1},
    {"action": "volume", "value": True},
    {"action": "volume", "value": 101},
])
def test_invalid_actions_are_rejected_before_dispatch(rig, payload):
    _, result, cookie = login(rig)
    status, _, _ = rig.request("POST", "/api/action", payload, cookie=cookie,
                               csrf=result["csrf"], origin=f"http://{rig.host}")
    assert status == 400
    assert rig.calls == []


def _envelope(rig, *, command_id="cmd-1", action="stop", payload=None):
    session_id, revision, _ = rig.server.fence.snapshot()
    return {
        "client_id": "phone-1", "command_id": command_id,
        "expected_session_id": session_id, "expected_revision": revision,
        "action": action, "payload": payload or {},
    }


def test_action_envelope_is_idempotent_and_fenced(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    envelope = _envelope(rig)
    status, body, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 202
    receipt = decode(body)
    assert receipt["ok"] and receipt["command_id"] == "cmd-1"
    assert rig.calls == [("stop", {"action": "stop"})]
    status, body, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 202 and decode(body) == receipt
    assert len(rig.calls) == 1


def test_altered_replay_and_stale_generation_are_rejected(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    envelope = _envelope(rig, action="seek", payload={"value": 1})
    status, _, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                               csrf=result["csrf"], origin=origin)
    assert status == 202
    altered = {**envelope, "payload": {"value": 2}}
    status, body, _ = rig.request("POST", "/api/action", altered, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 409 and decode(body)["conflict"] is True
    assert "revision" in decode(body)
    stale = {**_envelope(rig, command_id="cmd-2"),
             "expected_session_id": envelope["expected_session_id"],
             "expected_revision": envelope["expected_revision"]}
    status, body, _ = rig.request("POST", "/api/action", stale, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 409
    assert decode(body)["revision"] == rig.server.fence.snapshot()[1]
    assert len(rig.calls) == 1


@pytest.mark.parametrize("patch", [
    {"command_id": ""},
    {"command_id": "x" * 200},
    {"client_id": "bad id"},
    {"expected_session_id": "not-a-session"},
    {"expected_revision": -1},
    {"expected_revision": True},
    {"action": "cast"},
    {"payload": {"value": 1}},
])
def test_action_envelope_rejects_invalid_fields_before_dispatch(rig, patch):
    _, result, cookie = login(rig)
    envelope = _envelope(rig)
    envelope.update(patch)
    status, _, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                               csrf=result["csrf"], origin=f"http://{rig.host}")
    assert status == 400
    assert rig.calls == []


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_expired_session_is_rejected_before_dispatch():
    clock = _Clock()
    rig = PortalRig(clock=clock)
    try:
        _, result, cookie = login(rig)
        clock.now = portal.SESSION_SECONDS + 1
        status, _, _ = rig.request("POST", "/api/action", _envelope(rig), cookie=cookie,
                                   csrf=result["csrf"], origin=f"http://{rig.host}")
        assert status == 403
        assert rig.calls == []
    finally:
        rig.close()


def test_invalid_origin_and_unknown_paths_fail_closed(rig):
    status, _, _ = rig.request("POST", "/api/login", {"pin": PIN},
                               origin="https://127.0.0.1")
    assert status == 403
    status, _, _ = rig.request("GET", "/private/file")
    assert status == 404


def test_pin_is_not_written_to_request_logs(rig, capsys):
    status, _, _ = rig.request("POST", "/api/login", {"pin": "BADPIN"},
                               origin=f"http://{rig.host}")
    assert status == 401
    output = capsys.readouterr()
    assert "BADPIN" not in output.out + output.err


def test_ephemeral_port_and_clean_shutdown():
    server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, lambda *_args: {})
    assert server.server_address[1] > 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.shutdown()
    thread.join(2)
    assert not thread.is_alive()
    server.server_close()


def test_friendly_hostname_is_allowed_when_configured():
    server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, lambda *_args: {},
                                      hostname="smoothcast-lounge")
    try:
        port = server.server_address[1]
        assert server.host_allowed(f"smoothcast-lounge.local:{port}")
        assert server.host_allowed("smoothcast-lounge.local")
        assert not server.host_allowed("evil.example")
    finally:
        server.server_close()


def test_application_wires_portal_into_home_screen_and_closes_it():
    from gui_source import main_window_methods
    methods = main_window_methods()
    assert "_build_portal_card" in methods
    card = methods["_build_portal_card"]
    assert "portal_status_label" in card and "portal_url_label" in card
    assert "portal_pin_label" in card and "portal_activity_label" in card
    assert "portal_peers_box" in card
    assert "local network" in card
    assert "GLib.idle_add(run)" in methods["_portal_dispatch"]
    assert "self._refresh_portal()" in methods["__init__"]
    assert "self._stop_portal()" in methods["_on_close"]
    assert "_refresh_portal_activity" in methods["_refresh_portal"]
    assert "room.snapshot()" in methods["_refresh_portal_activity"]
    assert "In room:" in methods["_refresh_portal_activity"]
    assert "peer_discovery_available" in methods["_refresh_portal_activity"]
    assert "peer_discovery_ui.refresh_peer_links" in methods["_refresh_portal_activity"]
    peer_ui = Path(__file__).resolve().parents[1] / "src" / "peer_discovery_ui.py"
    assert "peer['id'][:6]" in peer_ui.read_text(encoding="utf-8")
    assert "mark_early_cast" in methods["_reconcile_portal_casts"]
    queue_actions = methods["_portal_queue_action"]
    for operation in ("queue_add", "queue_remove", "queue_move", "queue_play",
                      "queue_clear", "next", "previous"):
        assert operation in queue_actions
    assert "self.clear_queue()" in queue_actions
    assert "queue_revision" in queue_actions
    assert "_portal_observe_queue()" in methods["_portal_handle"]
    assert "portal_queue_id" in methods["_portal_queue_status"]
    assert "queue_durations" in methods["_portal_queue_status"]


def test_queue_ids_are_stable_without_leaking_paths():
    from cast_portal_queue import portal_queue_id
    first = portal_queue_id("/media/Films/One.mkv")
    assert first == portal_queue_id("/media/Films/One.mkv")
    assert first != portal_queue_id("/media/Films/Two.mkv")
    assert "media" not in first and "/" not in first


def test_upload_http_flow_authenticates_chunks_resumes_and_dispatches_staged_path(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        status, _, _ = rig.request("POST", "/api/uploads", {"name": "clip.mp4", "size": 6},
                                   origin=f"http://{rig.host}")
        assert status == 403
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "../clip.mp4", "size": 6, "queue": False},
                                     cookie=cookie, csrf=login_result["csrf"], origin=origin)
        assert status == 201
        created = decode(raw)
        upload_id = created["id"]
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie,
            extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        assert status == 403  # unauthenticated chunks never reach the store
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        assert status == 200 and decode(raw)["received"] == 3
        status, raw, _ = rig.request(
            "GET", f"/api/uploads/{upload_id}", cookie=cookie)
        assert status == 200 and decode(raw)["received"] == 3
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"def", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 3-5/6"},
            content_type="application/octet-stream")
        assert status == 200 and decode(raw)["complete"]
        status, raw, _ = rig.request("POST", f"/api/uploads/{upload_id}/complete", {},
                                     cookie=cookie, csrf=login_result["csrf"], origin=origin)
        assert status == 202 and decode(raw)["ok"]
        action, payload = rig.calls[-1]
        assert action == "cast_upload"
        assert Path(payload["path"]).read_bytes() == b"abcdef"
        assert Path(payload["path"]).parent == uploads.root
    finally:
        rig.close()
        uploads.close()


def test_queue_only_upload_dispatches_queue_add_by_default(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        status, raw, _ = rig.request(
            "POST", "/api/uploads", {"name": "clip.mkv", "size": 6, "queue": True},
            cookie=cookie, csrf=login_result["csrf"], origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abcdef", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 0-5/6"},
            content_type="application/octet-stream")
        assert status == 200
        status, raw, _ = rig.request(
            "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
            csrf=login_result["csrf"], origin=origin)
        assert status == 202
        assert decode(raw)["message"] == "Added to the shared queue."
        assert rig.calls[-1][0] == "queue_add"
        assert Path(rig.calls[-1][1]["path"]).read_bytes() == b"abcdef"
    finally:
        rig.close()
        uploads.close()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required")
def test_phone_audio_upload_is_validated_and_forced_into_shared_queue(tmp_path):
    import portal_uploads

    audio = tmp_path / "guest-track.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.5", "-c:a", "libmp3lame", "-y", str(audio)],
        check=True, capture_output=True, timeout=20,
    )
    data = audio.read_bytes()
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request(
            "POST", "/api/uploads",
            {"name": audio.name, "size": len(data), "queue": False},
            cookie=cookie, csrf=csrf, origin=origin,
        )
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", data, cookie=cookie,
            csrf=csrf, origin=origin,
            extra_headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
            content_type="application/octet-stream",
        )
        assert status == 200 and decode(raw)["ready_to_cast"] is False
        status, raw, _ = rig.request(
            "POST", f"/api/uploads/{upload_id}/complete", {"queue": False},
            cookie=cookie, csrf=csrf, origin=origin,
        )
        assert status == 202 and decode(raw)["message"] == "Added to the shared queue."
        action, payload = rig.calls[-1]
        assert action == "queue_add"
        assert Path(payload["path"]).read_bytes() == data
    finally:
        rig.close()
        uploads.close()


def test_upload_defaults_to_queue_when_intent_is_omitted(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads", early_cast_min_bytes=1)
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "clip.mkv", "size": 6},
                                     cookie=cookie, csrf=csrf, origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        body = decode(raw)
        assert status == 200 and body["ready_to_cast"] is False
        assert rig.calls == []
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"def", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 3-5/6"},
            content_type="application/octet-stream")
        assert status == 200
        status, _, _ = rig.request(
            "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
            csrf=csrf, origin=origin)
        assert status == 202
        assert rig.calls[-1][0] == "queue_add"
        assert Path(rig.calls[-1][1]["path"]).read_bytes() == b"abcdef"
    finally:
        rig.close()
        uploads.close()


def test_streamable_upload_starts_casting_before_it_finishes(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads", early_cast_min_bytes=1)
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "clip.mkv", "size": 6, "queue": False},
                                     cookie=cookie, csrf=csrf, origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        body = decode(raw)
        assert status == 200 and body["ready_to_cast"] is True
        action, payload = rig.calls[-1]
        assert action == "cast_upload" and payload["early"] is True
        assert payload["upload_id"] == upload_id
        assert uploads.by_id(upload_id)["phase"] == "casting"
        # Finalize still dispatches; the GUI dedupes by upload id.
        rig.request("PUT", f"/api/uploads/{upload_id}", b"def", cookie=cookie, csrf=csrf,
                    origin=origin, extra_headers={"Content-Range": "bytes 3-5/6"},
                    content_type="application/octet-stream")
        rig.request("POST", f"/api/uploads/{upload_id}/complete", {},
                    cookie=cookie, csrf=csrf, origin=origin)
        action, payload = rig.calls[-1]
        assert action == "cast_upload" and payload["early"] is False
    finally:
        rig.close()
        uploads.close()
