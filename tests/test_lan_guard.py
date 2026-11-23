"""#417: LAN boundary helpers and portal refusal of non-LAN peers."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import lan_guard


@pytest.mark.parametrize("address,expected", [
    ("127.0.0.1", True), ("10.1.2.3", True), ("172.16.0.9", True), ("172.31.255.1", True),
    ("192.168.1.50", True), ("169.254.3.4", True), ("::1", True), ("fe80::1%eth0", True),
    ("fd12:3456::1", True), ("::ffff:192.168.0.2", True),
    ("8.8.8.8", False), ("172.32.0.1", False), ("93.184.216.34", False),
    ("2001:4860:4860::8888", False), ("not-an-ip", False), ("", False), (None, False),
])
def test_is_lan_address(address, expected):
    assert lan_guard.is_lan_address(address) is expected


def test_allowed_hosts_include_entry_name_and_ports():
    hosts = lan_guard.allowed_hosts(["192.168.1.5"], 8080, ["Study-PC.local."])
    assert {"smoothcast.local:8080", "smoothcast.local", "192.168.1.5:8080",
            "study-pc.local", "localhost:8080"} <= hosts


def test_portal_refuses_non_lan_peer():
    import portal

    class Fake(portal._Handler):
        def __init__(self, ip):
            self.client_address = (ip, 1234)
            self.errors = []

        def send_error(self, code, *a, **k):
            self.errors.append(code)

    import http.server
    original = http.server.BaseHTTPRequestHandler.parse_request
    http.server.BaseHTTPRequestHandler.parse_request = lambda self: True
    try:
        public, private = Fake("8.8.8.8"), Fake("192.168.1.9")
        assert public.parse_request() is False and public.errors == [403]
        assert private.parse_request() is True and private.errors == []
    finally:
        http.server.BaseHTTPRequestHandler.parse_request = original
