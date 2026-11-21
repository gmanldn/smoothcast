"""#417: every listener keeps the trusted-home-LAN boundary."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_room_conformance import RoomHarness

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_router_port_mapping_code_exists():
    pattern = re.compile(r"AddPortMapping|AddAnyPortMapping|WANIPConnection|WANPPPConnection|natpmp|nat-pmp|miniupnp|upnpclient", re.I)
    hits = [p.name for p in SRC.glob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == [], f"the home LAN is the boundary; no router mapping allowed: {hits}"


@pytest.fixture
def room():
    harness = RoomHarness(count=1)
    yield harness
    harness.close()


def test_portal_rejects_bad_host_header(room):
    status, _, _ = room.request("GET", "/api/status", extra_headers={"Host": "evil.example"})
    assert status == 400


def test_portal_rejects_cross_origin_mutation(room):
    guest = room.login("Alice")
    status, _, _ = room.request(
        "POST", "/api/action", {"action": "stop"}, cookie=guest.cookie, csrf=guest.csrf,
        extra_headers={"Origin": "http://evil.example"})
    assert status in (400, 403)


@pytest.mark.parametrize("host", ["smoothcast.local", "localhost", "127.0.0.1"])
def test_portal_answers_to_entry_and_local_names(room, host):
    port = room.server.server_address[1]
    status, _, _ = room.request("GET", "/api/config", extra_headers={"Host": f"{host}:{port}"})
    assert status == 200


@pytest.mark.parametrize("path", ["/../etc/passwd", "/%2e%2e/etc/passwd", "/api/../../etc/passwd"])
def test_portal_does_not_serve_the_filesystem(room, path):
    status, _, _ = room.request("GET", path)
    assert status in (400, 403, 404)
