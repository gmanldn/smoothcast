"""SmoothCast service records are validated without LAN access."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import peer_discovery


INSTANCE = "a" * 32


def parse(**overrides):
    values = {
        "instance_id": INSTANCE,
        "name": "smoothcast-lounge",
        "version": "1",
        "capabilities": "room,unknown,remote-cast,video-upload",
        "addresses": ["192.168.1.25"],
        "port": 8765,
        "now": 10.0,
    }
    values.update(overrides)
    return peer_discovery.parse_peer(**values)


def test_service_record_exposes_only_validated_local_endpoint_and_known_capabilities():
    peer = parse()
    assert peer is not None
    assert peer.public() == {
        "id": INSTANCE,
        "name": "smoothcast-lounge",
        "version": 1,
        "compatible": True,
        "capabilities": ["remote-cast", "room", "video-upload"],
        "url": "http://192.168.1.25:8765/",
    }


@pytest.mark.parametrize("overrides", [
    {"instance_id": "bad"},
    {"instance_id": INSTANCE, "own_id": INSTANCE},
    {"name": "<img src=x>"},
    {"version": "1;secret"},
    {"version": "0"},
    {"port": 0},
    {"port": True},
    {"addresses": ["8.8.8.8"]},
    {"addresses": ["127.0.0.1"]},
    {"addresses": ["169.254.2.1"]},
])
def test_rejects_malformed_public_or_self_service_records(overrides):
    assert parse(**overrides) is None


def test_unknown_version_is_visible_but_incompatible():
    peer = parse(version="2")
    assert peer is not None
    assert peer.compatible is False


@pytest.mark.parametrize("bind_ip,name,port", [
    ("8.8.8.8", "smoothcast-host", 8765),
    ("192.168.1.2", "<host>", 8765),
    ("192.168.1.2", "smoothcast-host", True),
])
def test_directory_refuses_invalid_local_service_configuration(bind_ip, name, port):
    with pytest.raises(ValueError):
        peer_discovery.PeerDirectory(bind_ip, name, port)


class _FakeService:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def parsed_addresses(self):
        return ["192.168.1.25"]


class _FakeZeroconf:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.registered = []
        self.removed = []
        self.closed = False
        self.info = None

    def register_service(self, service):
        self.registered.append(service)

    def unregister_service(self, service):
        self.removed.append(service)

    def get_service_info(self, *_args, **_kwargs):
        return self.info

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, _zc, _service_type, *, listener):
        self.listener = listener
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def test_directory_keeps_idle_peers_until_dns_removal(monkeypatch):
    clock = [10.0]
    zc = _FakeZeroconf()
    monkeypatch.setattr(peer_discovery, "Zeroconf", lambda **_kwargs: zc)
    monkeypatch.setattr(peer_discovery, "ServiceInfo", _FakeService)
    monkeypatch.setattr(peer_discovery, "ServiceBrowser", _FakeBrowser)
    directory = peer_discovery.PeerDirectory(
        "192.168.1.10", "smoothcast-host", 8765,
        instance_id="b" * 32, clock=lambda: clock[0],
    )
    service = zc.registered[0]
    assert service.args[0] == peer_discovery.SERVICE_TYPE
    assert service.kwargs["port"] == 8765
    assert service.kwargs["host_ttl"] == service.kwargs["other_ttl"] == 45
    assert service.kwargs["properties"] == {
        "id": "b" * 32, "name": "smoothcast-host", "version": "1",
        "capabilities": ",".join(peer_discovery.LOCAL_CAPABILITIES),
    }
    assert directory.snapshot() == []

    info = _FakeService()
    info.properties = {
        b"id": INSTANCE.encode(), b"name": b"smoothcast-lounge",
        b"version": b"1", b"capabilities": b"room",
    }
    info.port = 9000
    zc.info = info
    directory.add_service(zc, peer_discovery.SERVICE_TYPE, "lounge")
    assert len(directory.snapshot()) == 1
    clock[0] += 300
    assert len(directory.snapshot()) == 1

    # Another advertisement for the same instance updates the endpoint.
    info.port = 9001
    directory.add_service(zc, peer_discovery.SERVICE_TYPE, "lounge-alias")
    assert [peer["url"] for peer in directory.snapshot()] == ["http://192.168.1.25:9001/"]
    directory.remove_service(zc, peer_discovery.SERVICE_TYPE, "lounge")
    assert len(directory.snapshot()) == 1
    directory.remove_service(zc, peer_discovery.SERVICE_TYPE, "lounge-alias")
    assert directory.snapshot() == []
    directory.close()
    assert directory._browser is None
    assert zc.closed is True
    assert zc.removed == [service]


def test_directory_caps_peer_count(monkeypatch):
    zc = _FakeZeroconf()
    monkeypatch.setattr(peer_discovery, "Zeroconf", lambda **_kwargs: zc)
    monkeypatch.setattr(peer_discovery, "ServiceInfo", _FakeService)
    monkeypatch.setattr(peer_discovery, "ServiceBrowser", _FakeBrowser)
    directory = peer_discovery.PeerDirectory("192.168.1.10", "smoothcast-host", 8765)
    for index in range(peer_discovery.MAX_PEERS + 4):
        info = _FakeService()
        info.properties = {
            b"id": (index + 1).to_bytes(16, "big").hex().encode(),
            b"name": f"smoothcast-{index}".encode(),
            b"version": b"1", b"capabilities": b"room,video-upload,remote-cast",
        }
        info.port = 9000
        zc.info = info
        directory.add_service(zc, peer_discovery.SERVICE_TYPE, f"host-{index}")
    assert len(directory.snapshot()) == peer_discovery.MAX_PEERS
    directory.close()


def test_directory_reuses_and_does_not_close_the_portal_zeroconf(monkeypatch):
    zc = _FakeZeroconf()
    monkeypatch.setattr(peer_discovery, "ServiceInfo", _FakeService)
    monkeypatch.setattr(peer_discovery, "ServiceBrowser", _FakeBrowser)
    directory = peer_discovery.PeerDirectory(
        "192.168.1.10", "smoothcast-host", 8765, zeroconf=zc,
    )
    directory.close()
    assert zc.closed is False
    assert len(zc.removed) == 1
