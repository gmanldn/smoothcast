"""Dedicated mesh heartbeat coordinator and its HTTP surface."""
from __future__ import annotations

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_heartbeat
import mesh_model as mm
import mesh_state
import portal_mesh_http


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def coordinator(sample, clock=None):
    clock = clock or Clock()
    return mesh_heartbeat.HeartbeatCoordinator(sample=lambda: sample, clock=clock, wall=clock)


# -- coordinator ---------------------------------------------------------------

def test_a_beat_sequences_reports_the_primary_and_has_no_internal_keys():
    hb = coordinator({"mesh_state": "running", "primary_id": "a" * 32, "primary_name": "Alpha",
                      "primary_self": False, "nodes": 2, "targets": 3, "targets_ready": 1,
                      "clients": 1, "generation": 5,
                      "activities": ["Alpha coordinates the mesh"]})
    hb.beat()
    snap = hb.snapshot()
    assert snap["state"] == "up"
    assert snap["seq"] == 1 and "_at" not in snap
    assert snap["primary"] == {"id": "a" * 32, "name": "Alpha", "self": False, "for_s": 0}
    assert (snap["nodes"], snap["targets"], snap["targets_ready"], snap["clients"]) == (2, 3, 1, 1)
    assert snap["activities"] == ["Alpha coordinates the mesh"]
    hb.beat()
    assert hb.snapshot()["seq"] == 2


def test_primary_change_restarts_the_for_seconds_counter():
    clock, primary = Clock(), {"id": "a" * 32}
    hb = mesh_heartbeat.HeartbeatCoordinator(
        sample=lambda: {"mesh_state": "running", "primary_id": primary["id"]},
        clock=clock, wall=clock)
    hb.beat()
    clock.advance(10)
    hb.beat()
    assert hb.snapshot()["primary"]["for_s"] == 10
    primary["id"] = "b" * 32
    clock.advance(3)
    hb.beat()
    assert hb.snapshot()["primary"]["for_s"] == 0


def test_states_reflect_mesh_state_and_primary_presence():
    hb = coordinator({"mesh_state": "running", "primary_id": None})
    hb.beat()
    assert hb.snapshot()["state"] == "no_primary" and hb.snapshot()["primary"] is None
    off = coordinator({"mesh_state": "disabled", "primary_id": None})
    off.beat()
    assert off.snapshot()["state"] == "mesh_off"


def test_age_tracks_time_since_the_last_beat():
    clock = Clock()
    hb = coordinator({"mesh_state": "running", "primary_id": "a" * 32}, clock)
    hb.beat()
    clock.advance(2.5)
    assert hb.snapshot()["age_ms"] == 2500


def test_a_raising_sample_is_contained_and_the_thread_keeps_running():
    calls = {"n": 0}

    def sample():
        calls["n"] += 1
        raise RuntimeError("boom")

    hb = mesh_heartbeat.HeartbeatCoordinator(sample=sample, interval_s=0.05)
    hb.start()                        # the first beat is contained too
    try:
        time.sleep(0.25)
        assert hb.running and hb.errors >= 1 and calls["n"] >= 2
    finally:
        hb.stop()
    assert not hb.running


def test_start_is_idempotent_and_stop_is_clean():
    hb = coordinator({"mesh_state": "running", "primary_id": "a" * 32})
    hb.start()
    hb.start()
    assert hb.running
    hb.stop()
    assert not hb.running


# -- describe ------------------------------------------------------------------

def test_describe_turns_a_beat_into_shared_display_text():
    text = mesh_heartbeat.describe({
        "state": "up", "seq": 4, "age_ms": 2000, "uptime_s": 90,
        "primary": {"name": "Alpha", "self": False, "for_s": 10},
        "nodes": 2, "targets": 3, "targets_ready": 1, "clients": 1,
        "activities": ["Alpha coordinates the mesh"]})
    assert text["primary"] == "Alpha" and text["state"] == "Up"
    assert text["beat"] == "#4 · 2 s ago" and text["uptime"] == "1 min 30 s"
    assert text["mesh"] == "2 nodes · 1 of 3 receivers ready · 1 client"
    assert text["activity"] == "Alpha coordinates the mesh"


def test_describe_of_a_missing_mesh_is_explicit():
    text = mesh_heartbeat.describe(None)
    assert text["state"] == "Mesh off" and text["primary"] == "—"
    assert "No mesh" in text["activity"]


# -- web route -----------------------------------------------------------------

class _Feed:
    generation = "gen"
    last_event = 3

    def __init__(self, view, primary):
        self._publisher = type("P", (), {"view": view})()
        self._primary = primary


class _Server:
    def __init__(self, feed, heartbeat):
        self.mesh_feed = feed
        self.mesh_heartbeat = heartbeat


class _Handler:
    def __init__(self, server, authed=True):
        self.server = server
        self._authed = authed
        self.sent = None
        self.errors = None

    def _authenticated(self):
        return self._authed

    def _send(self, code, body):
        self.sent = (code, body)

    def _error(self, code, message):
        self.errors = (code, message)


def _view():
    record = mm.NodeRecord(node_id="a" * 32, boot_id="b" * 32, name="Alpha")
    return mesh_state.MeshView(1, "a" * 32, (record,))


def test_heartbeat_route_returns_the_attached_reading():
    server = _Server(_Feed(_view(), lambda: "a" * 32), lambda: {"seq": 7, "state": "up"})
    handler = _Handler(server)
    assert portal_mesh_http.route(handler, "GET", "/api/mesh/heartbeat") is True
    assert handler.sent == (200, {"ok": True, "heartbeat": {"seq": 7, "state": "up"}})


def test_mesh_snapshot_carries_the_heartbeat():
    server = _Server(_Feed(_view(), lambda: "a" * 32), lambda: {"seq": 7, "state": "up"})
    handler = _Handler(server)
    assert portal_mesh_http.route(handler, "GET", "/api/mesh") is True
    code, body = handler.sent
    assert code == 200 and body["mesh"]["primary"] == "a" * 32
    assert body["mesh"]["heartbeat"] == {"seq": 7, "state": "up"}


def test_heartbeat_route_requires_auth_and_a_running_mesh():
    handler = _Handler(_Server(None, lambda: {"seq": 1}), authed=False)
    assert portal_mesh_http.route(handler, "GET", "/api/mesh/heartbeat") is True
    assert handler.errors == (401, "Enter the PIN shown in SmoothCast")
    handler = _Handler(_Server(None, lambda: {"seq": 1}))
    assert portal_mesh_http.route(handler, "GET", "/api/mesh/heartbeat") is True
    assert handler.errors == (503, "The mesh is not running")
