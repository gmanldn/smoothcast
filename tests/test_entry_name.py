"""#419: smoothcast.local follows the primary node; /nodes fallback page."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import entry_name
import lan_guard
import mesh_roles
import mesh_service
from test_room_conformance import RoomHarness


class FakeZeroconf:
    registered: list = []
    taken: set = set()
    closed = 0

    def __init__(self, ip):
        self.ip = ip

    def register_service(self, info):
        if info.server.rstrip(".") in FakeZeroconf.taken:
            raise RuntimeError("name in use")
        FakeZeroconf.registered.append(info.server.rstrip("."))

    def unregister_service(self, info):
        FakeZeroconf.registered.remove(info.server.rstrip("."))

    def close(self):
        FakeZeroconf.closed += 1


def Info(type_, name, **kw):
    return SimpleNamespace(type=type_, name=name, **kw)


@pytest.fixture(autouse=True)
def reset():
    FakeZeroconf.registered, FakeZeroconf.taken, FakeZeroconf.closed = [], set(), 0


def make():
    return entry_name.EntryName("192.168.1.5", 8080, zeroconf_factory=FakeZeroconf, info_factory=Info)


def test_candidate_names_are_deterministic():
    assert entry_name.candidate_names() == [
        "smoothcast.local", "smoothcast-2.local", "smoothcast-3.local",
        "smoothcast-4.local", "smoothcast-5.local"]


def test_primary_claims_and_release_follows_the_role():
    entry = make()
    entry.apply(False)
    assert FakeZeroconf.registered == [] and entry.name is None
    entry.apply(True)
    assert FakeZeroconf.registered == ["smoothcast.local"] and entry.url == "http://smoothcast.local:8080/"
    entry.apply(True)                                  # idempotent
    assert FakeZeroconf.registered == ["smoothcast.local"]
    entry.apply(False)
    assert FakeZeroconf.registered == [] and entry.name is None and FakeZeroconf.closed == 1


def test_conflict_falls_back_to_the_next_name_and_is_reported():
    FakeZeroconf.taken = {"smoothcast.local", "smoothcast-2.local"}
    entry = make()
    entry.apply(True)
    assert entry.name == "smoothcast-3.local" and FakeZeroconf.registered == ["smoothcast-3.local"]


def test_all_names_taken_registers_nothing_and_cleans_up():
    FakeZeroconf.taken = set(entry_name.candidate_names())
    entry = make()
    entry.apply(True)
    assert entry.name is None and FakeZeroconf.registered == [] and FakeZeroconf.closed == 1


def test_failures_never_raise():
    def boom(ip):
        raise OSError("no multicast")

    entry = entry_name.EntryName("192.168.1.5", 80, zeroconf_factory=boom, info_factory=Info)
    entry.apply(True)
    entry.apply(False)
    entry.close()
    assert entry.name is None


def test_close_releases_the_name():
    entry = make()
    entry.apply(True)
    entry.close()
    assert FakeZeroconf.registered == [] and entry.name is None


def test_mesh_primary_change_notifies_listeners_and_isolates_failures():
    seen = []
    stub = SimpleNamespace(cache=None, errors=0, node_id="me", primary_listeners=[
        lambda c: seen.append(c.new), lambda c: 1 / 0])
    change = mesh_roles.PrimaryChanged(None, "me", "first")
    mesh_service.MeshService._on_primary(stub, change)
    assert seen == ["me"] and stub.errors == 1


@pytest.mark.parametrize("host,ok", [
    ("smoothcast.local", True), ("smoothcast.local:8080", True), ("SmoothCast-3.local.", True),
    ("smoothcast-1.local", False), ("smoothcast.local.evil.com", False), ("evil.local", False),
    ("smoothcast.localx", False)])
def test_entry_host_matching(host, ok):
    assert lan_guard.is_entry_host(host) is ok


def test_portal_answers_to_numbered_entry_names_and_lists_nodes_safely():
    harness = RoomHarness(count=1)
    try:
        port = harness.server.server_address[1]
        harness.server.nodes_provider = lambda: [
            {"name": "<script>alert(1)</script>", "url": "http://192.168.1.9:80/"},
            {"name": "Bad", "url": "javascript:alert(1)"}, "junk"]
        from http.client import HTTPConnection
        conn = HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/nodes", headers={"Host": f"smoothcast-2.local:{port}"})
        reply = conn.getresponse()
        text = reply.read().decode()
        assert reply.status == 200 and 'href="http://192.168.1.9:80/"' in text
        assert "<script>" not in text and "javascript:" not in text
        assert "&lt;script&gt;" in text
    finally:
        harness.close()
