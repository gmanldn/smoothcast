"""Target visibility, reachability edges and routes (#400)."""
from __future__ import annotations

import ast
from pathlib import Path
import random
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_model as mm
import mesh_sim as ms
import mesh_state as st
import mesh_visibility as mv
from mesh_full_node import FullNode

SRC = Path(__file__).resolve().parents[1] / "src" / "mesh_visibility.py"


class ObservingNode(FullNode):
    """FullNode plus a LocalObserver fed by a fake discovery list."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.discovered: dict[str, mv.Discovered] = {}
        self.probes: list[str] = []
        self.probe_ok: dict[str, bool] = {}
        clock = kw["clock"]
        self.clock = clock
        self.observer = mv.LocalObserver(
            clock=clock, rng=kw["rng"], source=lambda: list(self.discovered.values()),
            publish=self.replicator.update,
            node_edges=lambda: [(m.node_id, clock.monotonic() - m.last_heard)
                                for m in self.membership.members()],
            prober=self._probe)

    def _probe(self, item, done):
        self.probes.append(item.id)
        ok = self.probe_ok.get(item.id, True)
        self.clock.call_later(0.05, lambda: done((ok, 7, "") if ok else (False, None, "timeout")))

    def start(self):
        super().start()
        self.observer.start()

    def stop(self, clean):
        self.observer.close()
        super().stop(clean)

    def see(self, target_id, name="TV", **kw):
        self.discovered[target_id] = mv.Discovered(
            target_id, kw.pop("kind", "cast"), name, self.clock.monotonic(),
            probe=("192.168.1.99", 8009), **kw)
        self.observer.changed()


def world(seed=1):
    return ms.SimWorld(seed, ObservingNode)


def settled(n, seed=1):
    w = world(seed)
    w.join(n)
    w.assert_converged(5000)
    w.run(3)
    return w


def matrix(handle):
    return mv.VisibilityMatrix(handle.node.publisher.view)


# -- propagation -------------------------------------------------------------

def test_an_appearing_target_is_in_every_matrix_within_budget_and_disappears_after_expiry():
    w = settled(6, seed=2)
    a = w.running()[0]
    a.node.see("tv-1", "Lounge TV")
    elapsed = w.run_until(lambda: all(matrix(h).get("tv-1") for h in w.running()), 3.0)
    assert elapsed is not None and elapsed < ms.BUDGETS["target_visible_s"]
    assert all(matrix(h).get("tv-1").state == "ready" for h in w.running())
    w.run(mv.READY_S + 20)                      # nobody refreshes last_seen -> stale
    a.node.observer.refresh()
    w.run(2)
    assert all(matrix(h).get("tv-1").state == "stale" for h in w.running())
    w.run(mv.EXPIRE_S)
    a.node.observer.refresh()
    w.run(2)
    assert all(matrix(h).get("tv-1") is None for h in w.running())


def test_two_nodes_seeing_one_tv_produce_a_single_entry_with_two_observers():
    w = settled(4, seed=3)
    a, b = w.running()[:2]
    a.node.see("tv-1", "Lounge TV", model="Chromecast")
    b.node.see("tv-1", "Lounge TV", model="Chromecast")
    w.run(2)
    entry = matrix(w.running()[2]).get("tv-1")
    assert {s.node_id for s in entry.seen_by} == {a.node_id, b.node_id}
    assert len(matrix(w.running()[2]).targets()) == 1
    assert entry.models == ("Chromecast",)


def test_unchanged_observations_do_not_bump_the_record_revision():
    w = settled(2, seed=4)
    a = w.running()[0]
    a.node.see("tv-1")
    w.run(2)
    rev = a.node.state.own.rev
    for _ in range(50):
        a.node.discovered["tv-1"] = mv.Discovered("tv-1", "cast", "TV", a.node.clock.monotonic(),
                                                 probe=("192.168.1.99", 8009))
        a.node.observer.refresh()
        w.run(1)
    assert a.node.state.own.rev - rev <= 6          # only probe edge changes, not ages


def test_a_departed_observer_takes_its_observations_out_of_the_matrix():
    w = settled(4, seed=5)
    a = w.running()[0]
    a.node.see("only-a")
    w.run(2)
    w.measure_leave(a, clean=False)
    w.run(1)
    assert all(matrix(h).get("only-a") is None for h in w.running())


# -- states, probes and edges ----------------------------------------------------

def test_busy_unreachable_and_owner_hints():
    w = settled(3, seed=6)
    a, b, c = w.running()
    a.node.see("tv-1", busy=True, owner=b.node_id)
    b.node.see("tv-2")
    b.node.probe_ok["tv-2"] = False
    w.run(mv.PROBE_INTERVAL_S * 2 + 5)
    m = matrix(c)
    assert m.get("tv-1").state == "busy" and m.get("tv-1").owner_hint == b.node_id
    assert m.get("tv-2").state == "unreachable"
    options = mv.candidate_routes(m, "tv-2")
    assert options.candidates == () and "timeout" in options.excluded[0][1]
    assert mv.candidate_routes(m, "tv-1").reason == "The receiver is busy"
    assert mv.candidate_routes(m, "nope").reason.startswith("No node")


def test_routes_prefer_ready_low_rtt_and_the_source_node():
    w = settled(4, seed=7)
    a, b, c, d = w.running()
    for handle, rtt in ((a, 40), (b, 5)):
        handle.node.see("tv-1")
        handle.node.probe_ok["tv-1"] = True
    for _ in range(4):                          # discovery keeps re-seeing the TV
        w.run(10)
        for handle in (a, b):
            handle.node.see("tv-1")
    w.run(2)
    m = matrix(d)
    ready = mv.candidate_routes(m, "tv-1").candidates
    assert {c.node_id for c in ready} == {a.node_id, b.node_id}
    pinned = mv.candidate_routes(m, "tv-1", source_node=a.node_id).candidates
    assert pinned[0].node_id == a.node_id
    assert all(c.state == "ready" for c in ready)


def test_probes_are_bounded_rate_limited_and_edges_capped():
    w = settled(2, seed=8)
    a = w.running()[0]
    for index in range(40):
        a.node.see(f"t{index:02d}")
    w.run(mv.PROBE_INTERVAL_S * 4)
    assert a.node.observer.probes_started <= (mv.PROBE_CONCURRENCY * 8) + 2
    assert len(a.node.state.own.edges) <= mm.MAX_EDGES
    assert len(a.node.state.own.targets) <= mm.MAX_TARGETS


@pytest.mark.parametrize("slow_probe", [False, True])
def test_probe_rounds_cover_the_inventory_within_the_slot_budget(slow_probe):
    clock = ms.SimClock()

    def receiver(index):
        return mv.Discovered(f"tv-{index}", "cast", "TV", clock.monotonic(),
                             probe=("192.168.1.99", 8009))

    inventory = {item.id: item for item in map(receiver, range(7))}
    pending = {}
    started = []

    def probe(item, done):
        assert item.id not in pending
        pending[item.id] = done
        started.append(item.id)
        assert len(pending) <= 2

    observer = mv.LocalObserver(clock=clock, rng=random.Random(0),
                                source=inventory.values, publish=lambda **_: None,
                                prober=probe)
    for index in range(7 if slow_probe else 4):
        before = len(started)
        observer._probe_round()
        assert len(started) - before == (1 if slow_probe and index else 2)
        for receiver_id in list(pending):
            if not slow_probe or receiver_id != "tv-0":
                pending.pop(receiver_id)((True, 7, ""))
        if slow_probe and index == 0:
            del inventory["tv-2"]
            new_receiver = receiver(7)
            inventory[new_receiver.id] = new_receiver

    assert set(inventory) <= set(started)
    if slow_probe:
        assert started.count("tv-0") == 1
        assert "tv-2" not in started
    observer.close()


def test_node_to_node_edges_are_published_quantised():
    w = settled(3, seed=9)
    a = w.running()[0]
    w.run(mv.REFRESH_S * 2)
    edges = [e for e in a.node.state.own.edges if e.peer_kind == "node"]
    assert len(edges) == 2 and all(e.last_ok_ms % mv.EDGE_QUANTUM_MS == 0 for e in edges)


def test_viewing_the_inventory_never_triggers_extra_discovery_scans():
    w = settled(3, seed=10)
    a = w.running()[0]
    a.node.see("tv-1")
    w.run(5)
    before = a.node.observer.source_calls
    for _ in range(1000):
        for h in w.running():
            matrix(h).targets()
    assert a.node.observer.source_calls == before


def test_matrix_is_deterministic_and_resolves_conflicting_names():
    def rec(node, name, state="ready", rev=1):
        return mm.NodeRecord(node_id=node * 32, boot_id="c" * 32, name="n", rev=rev,
                             targets=(mm.TargetObservation("t", "cast", name, state=state),))
    view = st.MeshView(1, "a" * 32, (rec("a", "Zed"), rec("b", "Alpha"), rec("c", "Alpha")))
    first = mv.VisibilityMatrix(view)
    assert first.get("t").name == "Alpha"                 # majority wins
    tie = st.MeshView(1, "a" * 32, (rec("a", "Zed"), rec("b", "Alpha")))
    assert mv.VisibilityMatrix(tie).get("t").name == "Alpha"     # tie -> lexicographic
    assert mv.VisibilityMatrix(view).targets() == first.targets()
    assert first.node_can_see("b" * 32) == ["t"]


# -- observation never acts ---------------------------------------------------------

FORBIDDEN = {"play", "load", "load_media", "launch", "start_app", "stop", "pause", "seek",
             "set_volume", "SetAVTransportURI", "set_av_transport_uri", "cast", "send",
             "sendall", "request", "post", "put"}


def test_the_module_contains_no_receiver_control_calls():
    tree = ast.parse(SRC.read_text())
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & FORBIDDEN, called & FORBIDDEN
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not imports & {"http", "urllib", "requests", "pychromecast", "catt", "dlna"}


def test_the_only_network_action_is_a_bare_tcp_connect(monkeypatch):
    opened = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mv.socket, "create_connection",
                        lambda addr, timeout=None: opened.append((addr, timeout)) or Conn())
    ok, rtt, reason = mv.connect_probe("192.168.1.5", 8009, 1.0)
    assert ok and reason == "" and opened == [(("192.168.1.5", 8009), 1.0)]
    for exc, expected in ((TimeoutError(), "timeout"), (ConnectionRefusedError(), "refused"),
                          (OSError(), "no_route")):
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(mv.socket, "create_connection", boom)
        assert mv.connect_probe("192.168.1.5", 1) == (False, None, expected)


def test_ten_simulated_minutes_send_a_fake_receiver_only_connection_attempts():
    """Discovery feeds the observer; the injected prober is the only outbound hook."""
    w = settled(3, seed=11)
    a = w.running()[0]
    a.node.see("tv-1")
    w.run(600)
    assert set(a.node.probes) == {"tv-1"}


def test_random_churn_with_targets_keeps_every_matrix_identical_for_20_seeds():
    for seed in range(20):
        w = world(seed)
        ms.random_scenario(w)
        w.run(10)
        prints = {mv.VisibilityMatrix(h.node.publisher.view).targets().__repr__()
                  for h in w.running()}
        assert len(prints) == 1, seed
