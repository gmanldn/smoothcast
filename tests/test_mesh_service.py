"""The mesh facade over real loopback sockets and threads (#405)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_service as svc
import mesh_visibility as mv

LOOP = "127.0.0.1"


def wait_for(predicate, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def mesh_threads():
    return {t.name for t in threading.enumerate() if t.name.startswith("smoothcast-mesh")}


def fds():
    return len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else 0


def make(tmp_path, name, **kw):
    cfg = svc.MeshConfig(bind_ip=LOOP, name=name, version="1.2.0", enabled=True,
                         multicast=False, beacon_port=0, state_dir=tmp_path / name, **kw)
    return svc.MeshService(cfg)


def link(a, b):
    a._udp.stand_in_peers = [f"{LOOP}:{b._udp.port}"]
    b._udp.stand_in_peers = [f"{LOOP}:{a._udp.port}"]


@pytest.fixture
def pair(tmp_path):
    seen = {"tv": []}
    a = make(tmp_path, "alpha", discovery=lambda: list(seen["tv"]))
    b = make(tmp_path, "beta")
    assert a.start() and b.start()
    link(a, b)
    yield a, b, seen
    a.stop()
    b.stop()


# -- switches and settings --------------------------------------------------------

def test_disabled_service_opens_nothing(tmp_path):
    before = mesh_threads(), fds()
    s = svc.MeshService(svc.MeshConfig(bind_ip=LOOP, enabled=False, state_dir=tmp_path))
    assert s.start() is False and s.status()["state"] == "disabled"
    assert s.view is None and s.subscribe() is None and s.diagnostics()["state"] == "disabled"
    s.stop()
    s.set_clients([], [])
    s.discovery_changed()
    assert (mesh_threads(), fds()) == before
    assert not list(tmp_path.iterdir())


def test_settings_default_off_and_are_validated(tmp_path):
    assert svc.load_settings(tmp_path / "missing.json") == {
        "enabled": False, "strict": False, "seeds": ()}
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mesh_enabled": True, "mesh_strict": "yes",
                                "mesh_seeds": ["192.168.1.4", "8.8.8.8", 5]}))
    got = svc.load_settings(path)
    assert got == {"enabled": True, "strict": False, "seeds": ("192.168.1.4",)}
    path.write_text("[1,2")
    assert svc.load_settings(path)["enabled"] is False
    path.write_text(json.dumps({"mesh_enabled": "true"}))
    assert svc.load_settings(path)["enabled"] is False


def test_identity_is_persistent_private_and_self_healing(tmp_path):
    path = tmp_path / "d" / "mesh_identity.json"
    first = svc.load_identity(path)
    assert len(first) == 32 and svc.load_identity(path) == first
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0
    path.write_text("{bad")
    second = svc.load_identity(path)
    assert second != first and svc.load_identity(path) == second
    assert svc.new_identity(path) != second


# -- real two-node mesh -------------------------------------------------------------

def test_two_services_find_each_other_sync_targets_and_see_departures(pair):
    a, b, seen = pair
    assert wait_for(lambda: len(a.view.nodes) == 2 and len(b.view.nodes) == 2), (
        a.diagnostics(), b.diagnostics())
    assert a.view.fingerprint() != "" and {n.name for n in a.view.nodes} == {"alpha", "beta"}
    seen["tv"].append(mv.Discovered("tv-1", "cast", "Lounge TV", time.monotonic()))
    a.discovery_changed()
    assert wait_for(lambda: "tv-1" in {t.id for _n, t in b.view.targets()})
    a.set_clients([{"id": "p1", "name": "Sam", "online": True}],
                  [{"id": "ab12", "name": "Kitchen", "ready": True, "video": True,
                    "state": "idle"}])
    assert wait_for(lambda: any(t.id == "screen-ab12" for _n, t in b.view.targets()))
    own_a = b.view.node(a.node_id)
    assert wait_for(lambda: len(b.view.node(a.node_id).clients) == 2), own_a
    primaries = [s.status()["primary"] for s in (a, b)]
    assert wait_for(lambda: sorted(s.status()["primary"] for s in (a, b)) == [False, True])
    assert primaries is not None
    b.stop(graceful=True)
    assert wait_for(lambda: len(a.view.nodes) == 1, 6.0)
    assert b.status()["state"] == "stopped"


def test_diagnostics_are_redacted_and_report_health(pair):
    a, b, _ = pair
    assert wait_for(lambda: len(a.view.nodes) == 2)
    diag = a.diagnostics()
    text = json.dumps(diag)
    assert a.node_id not in text and b.node_id not in text and "alpha" not in text
    assert LOOP not in text
    assert diag["peers"] == 1 and diag["join_latency_s"] is not None
    assert diag["bytes"]["sent"] > 0 and diag["bytes"]["received"] > 0
    assert diag["beacon"]["received"] > 0 and diag["replication"]["syncs"] >= 1
    assert "smoothcast-mesh" in diag["threads"]
    assert any(t.startswith("smoothcast-mesh") for t in diag["threads"])


def test_a_lonely_node_hints_that_multicast_may_be_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "MULTICAST_HINT_S", 0.0)
    s = make(tmp_path, "solo")
    assert s.start()
    time.sleep(0.2)
    assert "Multicast may be blocked" in s.diagnostics()["multicast_hint"]
    s.stop()


# -- lifecycle, leaks, containment ---------------------------------------------------------

def test_repeated_start_stop_leaks_no_threads_or_sockets(tmp_path):
    baseline_threads, baseline_fds = mesh_threads(), fds()
    for _ in range(15):
        s = make(tmp_path, "cycle")
        assert s.start() and s.start() is True            # idempotent
        s.stop()
        s.stop()
    assert wait_for(lambda: mesh_threads() == baseline_threads)
    assert fds() <= baseline_fds + 2


def test_startup_failures_are_contained(tmp_path):
    bad = svc.MeshService(svc.MeshConfig(bind_ip="8.8.8.8", enabled=True, state_dir=tmp_path))
    assert bad.start() is False
    assert bad.status()["state"] == "unavailable" and "ValueError" in bad.status()["error"]
    nowhere = svc.MeshService(svc.MeshConfig(          # not an address of this machine
        bind_ip="10.254.254.254", enabled=True, multicast=False, state_dir=tmp_path / "two"))
    assert nowhere.start() is False and nowhere.status()["state"] == "unavailable"
    assert "OSError" in nowhere.status()["error"] or "Error" in nowhere.status()["error"]
    nowhere.stop()
    assert wait_for(lambda: not mesh_threads())


def test_an_exception_in_a_mesh_callback_does_not_stop_the_mesh(tmp_path):
    calls = {"n": 0}

    def exploding():
        calls["n"] += 1
        raise RuntimeError("boom")

    errors = []
    s = make(tmp_path, "boom", discovery=exploding, on_error=errors.append)
    assert s.start()
    s.discovery_changed()
    assert wait_for(lambda: s.errors >= 1 and errors)
    assert s.status()["state"] == "running" and calls["n"] >= 1
    s.set_clients([{"id": "x", "name": "Sam", "online": True}], [])
    time.sleep(0.2)
    assert s.status()["state"] == "running"
    s.stop()


def test_restart_on_a_new_interface_address_keeps_the_identity(tmp_path):
    s = make(tmp_path, "mover")
    assert s.start()
    identity = s.node_id
    assert s.restart(LOOP) and s.node_id == identity and s.status()["state"] == "running"
    s.stop()
    assert s.restart("8.8.8.8") is False and s.status()["state"] == "unavailable"


def test_cache_is_written_and_available_for_warm_start(pair, monkeypatch):
    a, b, _ = pair
    assert wait_for(lambda: len(a.view.nodes) == 2)
    a._loop.call_soon_threadsafe(a._save_cache)
    assert wait_for(lambda: a.cache.counts()["peers"] == 1)
    warm = a.warm_start()
    assert [p.name for p in warm.peers] == ["beta"] and warm.peers[0].cached


# -- app hook (cast_mesh) ------------------------------------------------------------------

class FakeRoom:
    def snapshot(self):
        return {"participants": [{"id": "p1", "name": "Sam", "online": True}]}


class FakeScreens:
    def snapshot(self):
        return [{"id": "ab12", "name": "TV", "ready": True, "video": True, "state": "idle"}]


class FakeServer:
    mesh_feed = None
    screens = FakeScreens()


class FakePortal:
    name = "smoothcast-test"
    port = 8123
    room = FakeRoom()
    server = FakeServer()


class FakeWindow:
    def __init__(self):
        self._portal = FakePortal()


def test_app_hook_is_inert_when_disabled_and_never_raises(monkeypatch, tmp_path):
    import cast_mesh
    monkeypatch.setattr(svc, "load_settings",
                        lambda path=None: {"enabled": False, "strict": False, "seeds": ()})
    window = FakeWindow()
    before = mesh_threads()
    cast_mesh.start(window, LOOP)
    cast_mesh.push_clients(window)
    cast_mesh.stop(window)
    cast_mesh.stop(object())                      # no attributes at all
    cast_mesh.start(object(), LOOP)               # missing portal: still no raise
    assert getattr(window, "_mesh", None) is None and mesh_threads() == before


def test_app_hook_runs_the_mesh_attaches_the_feed_and_publishes_clients(monkeypatch, tmp_path):
    import cast_mesh
    monkeypatch.setattr(svc, "load_settings",
                        lambda path=None: {"enabled": True, "strict": False, "seeds": ()})
    monkeypatch.setattr(svc, "config_path", lambda: tmp_path / "config.json")
    window = FakeWindow()
    cast_mesh.start(window, LOOP)
    service = window._mesh
    assert wait_for(lambda: service.state in {"running", "unavailable"})
    if service.state == "running":
        assert wait_for(lambda: window._portal.server.mesh_feed is service.feed)
        cast_mesh.push_clients(window)
        assert wait_for(lambda: len(service.view.node(service.node_id).clients) == 2)
    cast_mesh.stop(window)
    assert window._mesh is None and window._portal.server.mesh_feed is None
    assert wait_for(lambda: not mesh_threads())


def test_app_hook_advertises_only_enabled_local_link_workers(monkeypatch, tmp_path):
    import cast_mesh
    from types import SimpleNamespace

    monkeypatch.setattr(svc, "load_settings",
                        lambda path=None: {"enabled": True, "strict": False, "seeds": ()})
    monkeypatch.setattr(svc, "config_path", lambda: tmp_path / "config.json")
    window = FakeWindow()
    # Private fake server, not the shared class-level fixture.
    window._portal = SimpleNamespace(
        name="smoothcast-test", port=8123, room=FakeRoom(),
        server=SimpleNamespace(mesh_feed=None, screens=FakeScreens(),
                               link_jobs=SimpleNamespace(capabilities=lambda: {
                                   "youtube": True, "magnet": False})))
    cast_mesh.start(window, LOOP)
    service = window._mesh
    try:
        assert service.config.link_acquisition_sources == ("youtube",)
        assert wait_for(lambda: service.state == "running")
        capabilities = service.view.node(service.node_id).capabilities
        assert "acquire-youtube-local" in capabilities
        assert "acquire-magnet-local" not in capabilities
    finally:
        cast_mesh.stop(window)
        assert wait_for(lambda: not mesh_threads())


def test_app_hook_feeds_scanned_receivers_into_the_mesh(monkeypatch, tmp_path):
    import cast_mesh
    from types import SimpleNamespace as NS
    monkeypatch.setattr(svc, "load_settings",
                        lambda path=None: {"enabled": True, "strict": False, "seeds": ()})
    monkeypatch.setattr(svc, "config_path", lambda: tmp_path / "config.json")
    window = FakeWindow()
    window.devices = [NS(name="Lounge TV", host="127.0.0.1", port=1, uuid="u1", model="Chromecast")]
    window.dlna_devices = []
    cast_mesh.start(window, LOOP)
    service = window._mesh
    assert wait_for(lambda: service.state == "running")
    cast_mesh.push_clients(window)
    assert wait_for(lambda: "Lounge TV" in {t.name for _n, t in service.view.targets()})
    window.devices = []
    cast_mesh.push_clients(window)
    cast_mesh.stop(window)
    assert wait_for(lambda: not mesh_threads())
