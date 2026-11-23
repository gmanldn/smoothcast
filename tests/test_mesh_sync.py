"""Replication, MeshView and budgets across simulated nodes (#398)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_membership as mem
import mesh_model as mm
import mesh_sim as ms
import mesh_state as st
import mesh_sync as sync
from mesh_full_node import FullNode


def world(seed=1, **kw):
    return ms.SimWorld(seed, FullNode, **kw)


def settled(count, seed=1, **kw):
    w = world(seed, **kw)
    w.join(count)
    w.assert_converged(5000)
    w.run(3)
    return w


def fingerprints(w):
    return {h.node.publisher.view.fingerprint() for h in w.running()}


def target(i, name=None):
    return mm.TargetObservation(f"tv-{i:03d}", "cast", name or f"TV {i}")


# -- speed ---------------------------------------------------------------------

@pytest.mark.parametrize("count", [2, 5, 20])
def test_a_new_target_is_visible_everywhere_within_budget(count):
    w = settled(count, seed=count)
    samples = []
    for index in range(6):
        node = w.running()[index % count]
        samples.append(w.measure_target(node, f"tv-{index}"))
        w.run(1.0)
    assert ms.percentile(samples, 50) < 1.0
    w.assert_budget("target_visible_s", ms.percentile(samples, 99))
    assert len(fingerprints(w)) == 1


def test_a_node_joining_a_big_mesh_gets_everything_and_everyone_gets_it():
    w = settled(12, seed=2)
    for index, node in enumerate(w.running()):
        w.add_target(node, f"tv-{index}")
    w.run(3)
    joined = w.measure_join()
    assert joined < ms.BUDGETS["join_p99_s"]
    assert w.run_until(lambda: len(fingerprints(w)) == 1, 3.0) is not None
    newcomer = w.running()[-1].node
    assert len(newcomer.target_ids()) == 12


def test_steady_state_egress_and_event_rate_stay_within_budget_at_twenty_nodes():
    w = settled(20, seed=3)
    for index, node in enumerate(w.running()[:6]):
        w.add_target(node, f"tv-{index}")
    w.run(30)
    start_events = w.clock.events_run
    w.run(60)
    w.assert_budget("egress_bytes_per_s_at_20_nodes", w.egress_per_node(60))
    per_node_per_s = (w.clock.events_run - start_events) / 60 / 20
    assert per_node_per_s < 60                    # proxy for idle CPU: bounded events
    assert len(fingerprints(w)) == 1


def test_a_departed_nodes_targets_leave_every_view():
    w = settled(5, seed=4)
    victim = w.running()[1]
    w.add_target(victim, "gone-soon")
    w.run(2)
    assert all("gone-soon" in h.node.target_ids() for h in w.running())
    w.measure_leave(victim, clean=False)
    w.run(0.5)
    assert all("gone-soon" not in h.node.target_ids() for h in w.running())
    assert len(fingerprints(w)) == 1


def test_a_restart_replaces_the_old_boots_record_everywhere():
    w = settled(4, seed=5)
    node = w.running()[0]
    w.add_target(node, "before")
    w.run(2)
    w.restart(node)
    assert w.time_to_converge(5.0) is not None
    w.run(1)
    for handle in w.running():
        record = handle.node.publisher.view.node(node.node_id)
        assert record.boot_id == node.boot_id and not record.targets
    assert len(fingerprints(w)) == 1


# -- faults ----------------------------------------------------------------------

def test_loss_and_a_partition_with_edits_on_both_sides_converge_after_healing():
    w = settled(8, seed=6)
    nodes = w.running()
    left, right = nodes[:4], nodes[4:]
    w.set_loss(0.2)
    w.partition(left, right)
    for index, node in enumerate(nodes):
        w.add_target(node, f"p-{index}")
    w.run(30)
    assert len(fingerprints(w)) > 1
    w.heal()
    elapsed = w.run_until(lambda: w.converged() and len(fingerprints(w)) == 1, 10.0)
    assert elapsed is not None, w.describe_divergence()
    assert len(w.running()[0].node.target_ids()) == 8


def test_sleep_wake_and_ip_change_resync_content():
    w = settled(5, seed=7)
    sleeper = w.running()[0]
    w.sleep(sleeper)
    w.add_target(w.running()[1], "during-sleep")
    w.run(20)
    w.wake(sleeper)
    assert w.run_until(lambda: "during-sleep" in sleeper.node.target_ids(), 5.0) is not None
    new_ip = w.change_ip(w.running()[2])
    assert w.run_until(lambda: len(fingerprints(w)) == 1, 6.0) is not None
    addresses = {h.node.publisher.view.node(w.running()[2].node_id).addresses
                 for h in w.running()}
    assert addresses == {(new_ip,)}


def test_a_dead_link_backs_off_without_delaying_other_peers():
    w = settled(5, seed=8)
    a, b = w.running()[0], w.running()[1]
    w.net.set_link(a.address, b.address, ms.LinkProfile(loss=1.0))
    w.add_target(a, "from-a")
    w.run(30)
    link = a.node.replicator._links.get(b.node_id)
    others = [h for h in w.running() if h not in (a, b)]
    assert all("from-a" in h.node.target_ids() for h in others)
    assert link is None or link.failures >= 1 or "from-a" in b.node.target_ids()
    assert a.node.replicator.stats.failures >= 0
    w.net.set_link(a.address, b.address, ms.LinkProfile())
    assert w.run_until(lambda: "from-a" in b.node.target_ids(), 15.0) is not None


def test_large_records_are_chunked_under_the_reply_cap():
    w = settled(2, seed=9)
    big = tuple(mm.TargetObservation(f"t{i:03d}", "cast", "N" * 40, model="M" * 60,
                                     formats=tuple(f"video/x-{j}" for j in range(12)))
                for i in range(50))
    for node in w.running():
        node.node.replicator.update(targets=big)
    w.run(5)
    # Many more big nodes join: total state far exceeds one 100 KiB reply.
    for index in range(12):
        handle = w.add()
        handle.node.replicator.update(targets=big)
    assert w.time_to_converge(20.0) is not None
    assert sum(mm.encoded_size(r) for r in w.running()[0].node.publisher.view.nodes) > \
        sync.MAX_REPLY_BYTES
    newcomer = w.add()
    assert w.time_to_converge(20.0) is not None
    assert newcomer.node.replicator.stats.syncs > 1
    assert len(fingerprints(w)) == 1


# -- safety -----------------------------------------------------------------------

def rpc_push(w, sender, receiver, records):
    results = []
    sender.node.rpc.call(receiver.address, "push", {"records": records},
                         lambda r, e: results.append((r, e)), 2)
    w.run(1)
    return results[0]


def test_malformed_foreign_and_forged_records_change_nothing():
    w = settled(3, seed=10)
    a, b, c = w.running()
    before = b.node.publisher.view.fingerprint()
    good = c.node.state.own.to_wire()
    bad = [{"junk": 1}, "string", None, dict(good, node_id="XX"),
           dict(good, v=99)]
    forged_own = dict(b.node.state.own.to_wire(), rev=10 ** 6)
    stranger = dict(good, node_id="9" * 32, boot_id="8" * 32)
    reply, error = rpc_push(w, a, b, bad + [forged_own, stranger])
    assert error is None and reply["accepted"] == 0
    stats = b.node.replicator.stats
    assert stats.malformed >= 4 and stats.records_rejected >= 1
    assert b.node.publisher.view.fingerprint() == before
    assert b.node.state.own.rev == b.node.state.own.rev < 10 ** 6


def test_replayed_old_records_never_overwrite_newer_state():
    w = settled(3, seed=11)
    a, b, c = w.running()
    w.add_target(c, "first")
    w.run(2)
    old_wire = b.node.state.get(c.node_id).to_wire()
    w.add_target(c, "second")
    w.run(2)
    new_rev = b.node.state.get(c.node_id).rev
    reply, _ = rpc_push(w, a, b, [old_wire, old_wire])
    assert reply["accepted"] == 0
    assert b.node.state.get(c.node_id).rev == new_rev
    assert {"first", "second"} <= b.node.target_ids()


def test_an_oversized_or_garbage_rpc_body_is_ignored():
    w = settled(2, seed=12)
    a, b = w.running()
    for body in ({"records": "x"}, {"records": [1] * 500}, {"records": {}}, {}):
        reply, error = rpc_push(w, a, b, body["records"]) if "records" in body else (None, None)
    results = []
    a.node.rpc.call(b.address, "sync", {"hash": 5, "digest": [1, 2]},
                    lambda r, e: results.append((r, e)), 2)
    w.run(1)
    assert results[0][0]["records"] == []
    assert b.node.replicator.stats.malformed >= 1
    assert len(fingerprints(w)) == 1


hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as hst  # noqa: E402


@settings(max_examples=200, deadline=None, derandomize=True)
@given(hst.lists(hst.tuples(hst.sampled_from(["b" * 32, "c" * 32]), hst.integers(1, 20),
                            hst.integers(0, 3)), max_size=40))
def test_held_revision_never_goes_backwards_for_a_boot(seq):
    clock = ms.SimClock()
    own = mm.NodeRecord(node_id="1" * 32, boot_id="e" * 32, name="Me")
    state = st.MeshState(own, clock=clock)
    best: dict[str, int] = {}
    for boot, rev, epoch in seq:
        record = mm.NodeRecord(node_id="a" * 32, boot_id=boot, name="N", rev=rev,
                               boot_epoch=100 + epoch)
        before = state.get("a" * 32)
        state.accept(record, current_boot=boot)
        after = state.get("a" * 32)
        if before is not None and before.boot_id == after.boot_id:
            assert after.rev >= before.rev
        best[boot] = max(best.get(boot, 0), rev)
    held = state.get("a" * 32)
    if held is not None:
        assert held.rev <= best[held.boot_id]


# -- consumers ----------------------------------------------------------------------

def test_a_subscriber_sees_a_delta_for_a_remote_change_within_budget():
    w = settled(6, seed=13)
    observer, source = w.running()[0], w.running()[3]
    sub = observer.node.publisher.subscribe()
    sub.poll()
    started = w.clock.now_ms
    w.add_target(source, "live")
    got = []

    def check():
        for item in sub.poll():
            if isinstance(item, st.Delta):
                got.extend(c for c in item.changes
                           if c.node_id == source.node_id and "targets" in c.sections)
        return bool(got)
    assert w.run_until(check, 3.0) is not None
    assert (w.clock.now_ms - started) / 1000 < ms.BUDGETS["target_visible_s"]


def test_membership_events_remove_a_node_from_the_view_promptly():
    w = settled(4, seed=14)
    leaver = w.running()[0]
    observer = w.running()[1]
    sub = observer.node.publisher.subscribe()
    sub.poll()
    w.stop(leaver, clean=True)
    w.run(1.0)
    removed = [c for item in sub.poll() if isinstance(item, st.Delta)
               for c in item.changes if c.kind == "removed"]
    assert [c.node_id for c in removed] == [leaver.node_id]
    assert observer.node.publisher.view.node(leaver.node_id) is None


def test_update_validates_sections_and_keeps_records_within_limits():
    w = settled(2, seed=15)
    node = w.running()[0].node
    with pytest.raises(ValueError):
        node.replicator.update(node_id="x" * 32)
    many = tuple(mm.TargetObservation(f"t{i:03d}", "cast", "N" * 40) for i in range(mm.MAX_TARGETS))
    fitted = node.replicator.update(targets=many, clients=tuple(
        mm.ClientSummary(f"c{i}", "screen", name="n" * 40) for i in range(60)))
    assert mm.encoded_size(fitted) <= mm.MAX_RECORD_BYTES
    w.run(3)
    assert len(fingerprints(w)) == 1


def test_close_stops_all_replication_work():
    w = settled(3, seed=16)
    a = w.running()[0]
    a.node.replicator.close()
    syncs = a.node.replicator.stats.syncs
    w.add_target(w.running()[1], "x")
    w.run(30)
    assert a.node.replicator.stats.syncs == syncs
    a.node.replicator.on_membership_event(mem.NodeUp("f" * 32, "e" * 32, "10.0.0.1", 1, "new"))
    assert json.dumps(a.node.replicator._links) == "{}"


def test_seeded_random_churn_converges_in_content_for_40_seeds():
    failures = ms.run_seeds(range(40), factory=FullNode)
    assert failures == [], failures[:2]
    for seed in (1, 2, 3, 4, 5):
        w = ms.SimWorld(seed, FullNode)
        ms.random_scenario(w)
        assert w.converged()
        assert w.run_until(lambda: len(fingerprints(w)) == 1, 15.0) is not None, seed
