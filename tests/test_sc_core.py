"""The always-on sc-core coordinator: light, bounded, self-healing, GTK-free."""
from __future__ import annotations

import pytest

import sc_core


@pytest.fixture(autouse=True)
def _no_real_lan(monkeypatch):
    # Never let a real ScCore open sockets or start a real mesh in unit tests.
    monkeypatch.setattr(sc_core.lan_interfaces, "select_private_lan_ip", lambda: None)


class FakeMesh:
    def __init__(self, state="running", beat=None):
        self.state = state
        self._beat = beat or {}

    def status(self):
        return {"state": self.state}

    def heartbeat_snapshot(self):
        return self._beat


class FakeWindow:
    def __init__(self, mesh=None):
        self._mesh = mesh
        self._closing = False
        self.session = None
        self.tracker = None
        self.external = False


def core(window, *, address="192.168.1.10", clock=None, starts=None):
    calls = starts if starts is not None else []
    return sc_core.ScCore(
        window,
        clock=clock or (lambda: 100.0),
        wall=lambda: 1_700_000_000.0,
        resolve=lambda: address,
        mesh_start=lambda win, addr: calls.append((win, addr)),
    )


def test_core_starts_the_mesh_when_it_is_down():
    window = FakeWindow(mesh=None)
    calls: list = []
    c = core(window, starts=calls)
    c.tick()
    assert calls == [(window, "192.168.1.10")]
    snap = c.snapshot()
    assert snap["address"] == "192.168.1.10"
    assert snap["seq"] == 1
    assert snap["mesh"]["state"] == "off"


def test_core_never_restarts_a_running_mesh():
    window = FakeWindow(mesh=FakeMesh(state="running"))
    calls: list = []
    core(window, starts=calls).tick()
    assert calls == []


def test_core_restarts_a_stopped_mesh():
    window = FakeWindow(mesh=FakeMesh(state="stopped"))
    calls: list = []
    core(window, starts=calls).tick()
    assert len(calls) == 1


def test_core_is_dormant_without_a_private_lan():
    window = FakeWindow(mesh=None)
    calls: list = []
    c = core(window, address=None, starts=calls)
    c.tick()
    assert calls == []
    assert c.snapshot()["address"] is None


def test_core_never_raises_and_counts_a_failing_resolver():
    def boom():
        raise OSError("no interfaces")

    c = sc_core.ScCore(FakeWindow(), clock=lambda: 1.0, resolve=boom,
                       mesh_start=lambda win, addr: None)
    c.tick()                                   # must not raise
    assert c.errors == 1 and "OSError" in c.last_error


def test_snapshot_is_bounded_and_reports_web_clients():
    beat = {"nodes": 3, "targets": 9, "targets_ready": 4, "clients": 7,
            "activities": ["a", "b", "c", "d", "e", "f"]}
    window = FakeWindow(mesh=FakeMesh(beat=beat))
    c = core(window)
    c.tick()
    mesh = c.snapshot()["mesh"]
    assert (mesh["nodes"], mesh["receivers"], mesh["receivers_ready"],
            mesh["clients"]) == (3, 9, 4, 7)
    assert mesh["activities"] == ["a", "b", "c", "d"]     # MAX_ACTIVITIES cap


def test_cast_summary_reads_the_published_status_only():
    class Status:
        def read(self):
            return {"active": True, "state": "PLAYING", "mode": "transcode",
                    "target": "Lounge TV", "path": "/private/x.mkv"}

    window = FakeWindow()
    window._core_status = Status()
    c = core(window)
    c.tick()
    cast = c.snapshot()["cast"]
    assert cast == {"active": True, "state": "PLAYING", "mode": "transcode",
                    "target": "Lounge TV"}                 # never a path


def test_core_never_touches_playback():
    window = FakeWindow()
    session = object()
    tracker = object()
    window.session, window.tracker = session, tracker
    c = core(window)
    c.tick()
    assert window.session is session and window.tracker is tracker


def test_start_is_idempotent_and_stop_joins_the_thread():
    window = FakeWindow()
    c = core(window)
    c.start()
    first = c._thread
    assert c.running is True
    assert c.start() is c and c._thread is first      # no second thread
    c.stop()
    assert c.running is False


def test_module_helpers_attach_and_detach_the_coordinator():
    window = FakeWindow()
    sc_core.stop(window)                              # idempotent before start
    started = sc_core.start(window)
    assert window._sc_core is started and started.running is True
    assert sc_core.snapshot(window) is not None
    sc_core.stop(window)
    assert getattr(window, "_sc_core", None) is None
    assert sc_core.snapshot(window) is None


def test_core_thread_is_a_daemon():
    window = FakeWindow()
    c = core(window)
    c.start()
    try:
        assert c._thread is not None and c._thread.daemon is True
        assert c._thread.name == "smoothcast-sc-core"
    finally:
        c.stop()
