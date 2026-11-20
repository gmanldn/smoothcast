"""LAN dashboard HTTP behavior using only a private loopback test listener."""
from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


PIN = "234567"


class PortalRig:
    def __init__(self):
        self.calls = []

        def dispatch(action, payload):
            self.calls.append((action, payload))
            if action == "status":
                return {"title": "sample.mp4", "state": "PLAYING", "queue": []}
            return "accepted"

        self.server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, dispatch)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def request(self, method, path, body=None, *, cookie=None, csrf=None, origin=None, host=None):
        headers = {"Host": host or self.host}
        if origin is not None:
            headers["Origin"] = origin
        if cookie:
            headers["Cookie"] = cookie
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if body is not None:
            import json
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
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


def test_pin_is_six_securely_selected_readable_characters():
    assert len(portal.new_pin()) == portal.PIN_LENGTH
    assert set(portal.new_pin()).issubset(set(portal.PIN_ALPHABET))
    choices = iter("AB2345")
    assert portal.new_pin(choice=lambda _alphabet: next(choices)) == "AB2345"


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


def test_status_requires_a_pin_and_rejects_host_rebinding(rig):
    status, body, _ = rig.request("GET", "/api/status")
    assert status == 401 and decode(body)["ok"] is False
    status, _, _ = rig.request("GET", "/api/status", host="evil.example")
    assert status == 400
    assert rig.calls == []


def login(rig, pin=PIN):
    status, body, headers = rig.request("POST", "/api/login", {"pin": pin},
                                        origin=f"http://{rig.host}")
    return status, decode(body), headers.get("Set-Cookie", "").split(";", 1)[0]


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


def test_application_wires_portal_into_home_screen_and_closes_it():
    from gui_source import main_window_methods
    methods = main_window_methods()
    assert "_build_portal_card" in methods
    card = methods["_build_portal_card"]
    assert "portal_status_label" in card and "portal_url_label" in card
    assert "portal_pin_label" in card and "local network" in card
    assert "GLib.idle_add(run)" in methods["_portal_dispatch"]
    assert "self._refresh_portal()" in methods["__init__"]
    assert "self._stop_portal()" in methods["_on_close"]
