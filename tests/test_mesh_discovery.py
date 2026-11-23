"""Cast/DLNA scan results -> mesh target observations (#405)."""
from __future__ import annotations

from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_discovery as md
import mesh_model as mm
import mesh_service as svc
import mesh_visibility as mv


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def cast(name="Lounge TV", host="192.168.1.50", uuid="ABCD-1234", port=8009, model="Chromecast"):
    return NS(name=name, host=host, port=port, uuid=uuid, model=model)


def dlna(name="Bedroom", host="192.168.1.60", loc="http://192.168.1.60:49152/desc.xml"):
    return NS(name=name, host=host, location=loc, model="Bravia", key=f"DLNA · {name} · {host}")


def test_ids_are_stable_valid_and_do_not_depend_on_the_name_when_a_uuid_exists():
    a, b = cast(name="Old name"), cast(name="Renamed")
    assert md.cast_id(a) == md.cast_id(b) == "cast-abcd-1234"
    no_uuid = md.cast_id(cast(uuid=""))
    assert no_uuid.startswith("cast-") and no_uuid == md.cast_id(cast(uuid=""))
    assert md.cast_id(cast(uuid="../x")) != "cast-../x"
    assert md.dlna_id(dlna()) == md.dlna_id(dlna(name="Other name"))
    for ident in (md.cast_id(a), no_uuid, md.dlna_id(dlna())):
        mm.TargetObservation(ident, "cast", "x")                  # passes the model's id rule


def test_snapshot_marks_present_receivers_fresh_and_absent_ones_age_then_expire():
    clock = Clock()
    ad = md.DiscoveryAdapter(clock=clock)
    assert ad.update([cast()], [dlna()]) is True
    kinds = {d.id: d for d in ad.snapshot()}
    assert {d.kind for d in kinds.values()} == {"cast", "dlna"}
    assert all(d.last_seen == clock.t for d in kinds.values())
    clock.t += 100                                    # scans are rare: still present => fresh
    assert all(d.last_seen == clock.t for d in ad.snapshot())
    assert ad.update([cast()], []) is True            # the DLNA TV vanished
    clock.t += 40
    seen = {d.id: d.last_seen for d in ad.snapshot()}
    assert seen[md.dlna_id(dlna())] == clock.t - 40 and seen[md.cast_id(cast())] == clock.t
    clock.t += mv.EXPIRE_S
    ad.update([cast()], [])
    assert [d.kind for d in ad.snapshot()] == ["cast"]


def test_changes_are_reported_only_when_the_receiver_set_or_names_change():
    ad = md.DiscoveryAdapter(clock=Clock())
    assert ad.update([cast()], []) is True
    assert ad.update([cast()], []) is False
    assert ad.update([cast(name="Renamed")], []) is True
    assert ad.update([], []) is True and ad.update(None, None) is False


def test_probe_targets_are_private_hosts_with_real_ports_only():
    ad = md.DiscoveryAdapter(clock=Clock())
    ad.update([cast(host="8.8.8.8"), cast(name="Odd port", uuid="u2", host="192.168.1.9", port=0)],
              [dlna(loc="http://192.168.1.60:70000/x"), dlna(name="ok", loc="http://192.168.1.61:1234/x",
                                                             host="192.168.1.61")])
    probes = {d.name: d.probe for d in ad.snapshot()}
    assert probes["Lounge TV"] is None                              # public host: never probed
    assert probes["Odd port"] == ("192.168.1.9", 8009)
    assert probes["ok"] == ("192.168.1.61", 1234)
    assert probes["Bedroom"] is None                                # bad port


def test_hostile_or_odd_scan_objects_never_raise():
    ad = md.DiscoveryAdapter(clock=Clock())
    ad.update([NS(), NS(name=None, host=None, uuid=None, port="x" if False else 0)],
              [NS(location="::::"), NS(location="http://[bad", host="")])
    assert len(ad.snapshot()) >= 1
    many = [cast(uuid=f"u{i}") for i in range(500)]
    ad.update(many, [])
    assert len(ad.snapshot()) <= md._MAX * 2 + 10


def test_observer_publishes_real_looking_targets_from_the_adapter():
    clock = Clock()
    ad = md.DiscoveryAdapter(clock=clock)
    ad.update([cast()], [dlna()])
    published = []
    obs = mv.LocalObserver(clock=SimClockShim(clock), rng=__import__("random").Random(1),
                           source=ad.snapshot, publish=lambda **kw: published.append(kw))
    assert obs.refresh() is True
    targets = {t.name: t for t in published[0]["targets"]}
    assert targets["Lounge TV"].kind == "cast" and targets["Lounge TV"].state == "ready"
    assert targets["Bedroom"].kind == "dlna" and targets["Bedroom"].model == "Bravia"


class SimClockShim:
    def __init__(self, clock):
        self._c = clock

    def monotonic(self):
        return self._c()

    def call_later(self, delay, cb):
        return SimpleTimer()


class SimpleTimer:
    def cancel(self):
        pass


def test_service_probes_receivers_off_the_mesh_loop_and_reports_unreachable(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    open_port = listener.getsockname()[1]
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    ad = md.DiscoveryAdapter()
    ad.update([cast(name="Up", host="127.0.0.1", port=open_port, uuid="up"),
               cast(name="Down", host="127.0.0.1", port=dead_port, uuid="down")], [])
    s = svc.MeshService(svc.MeshConfig(
        bind_ip="127.0.0.1", name="probe", version="1.2.0", enabled=True, multicast=False,
        beacon_port=0, state_dir=tmp_path, discovery=ad.snapshot))
    try:
        assert s.start()
        s._loop.call_soon_threadsafe(s._probe_round_now)
        end = time.monotonic() + 8
        states = {}
        while time.monotonic() < end:
            view = s.view
            states = {t.name: t.state for _n, t in view.targets()}
            if states.get("Down") == "unreachable" and states.get("Up") == "ready":
                break
            time.sleep(0.05)
        assert states == {"Up": "ready", "Down": "unreachable"}, states
        edges = {e.peer: e for e in s.view.node(s.node_id).edges if e.peer_kind == "target"}
        assert edges[md.cast_id(cast(uuid="down"))].reason in {"refused", "timeout", "no_route"}
        assert edges[md.cast_id(cast(uuid="up"))].rtt_ms is not None
    finally:
        s.stop()
        listener.close()
    assert not [t for t in threading.enumerate() if t.name.startswith("smoothcast-mesh-probe")]
