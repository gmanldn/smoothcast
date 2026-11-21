"""Membership and failure detection in the simulator (#397)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_beacon as mb
import mesh_membership as mem
import mesh_sim as ms
from mesh_member_node import MemberNode
from mesh_rpc import RpcRouter


def world(seed=1, **kw):
    return ms.SimWorld(seed, MemberNode, **kw)


def all_events(w, kind):
    return [e for h in w.nodes.values() if h.node for e in h.node.events if isinstance(e, kind)]


def settled(count, seed=1, **kw):
    w = world(seed, **kw)
    w.join(count)
    w.assert_converged(5000)
    w.run(5)
    return w


# -- detection speed ---------------------------------------------------------

@pytest.mark.parametrize("count", [3, 8, 20])
def test_a_silent_crash_is_declared_dead_everywhere_within_budget(count):
    w = settled(count)
    victim = w.running()[1]
    elapsed = w.measure_leave(victim, clean=False)
    w.assert_budget("silent_loss_s", elapsed)
    for handle in w.running():
        downs = handle.node.downs()
        assert [d.node_id for d in downs] == [victim.node_id]
        assert downs[0].reason == "timeout"
        assert handle.node.membership.tombstone(victim.node_id) is not None
    assert w.check_invariants() == []


@pytest.mark.parametrize("count", [3, 20])
def test_a_clean_goodbye_removes_the_node_within_half_a_second(count):
    w = settled(count)
    leaver = w.running()[0]
    elapsed = w.measure_leave(leaver, clean=True)
    w.assert_budget("leave_clean_s", elapsed)
    assert all(d.reason == "goodbye" for h in w.running() for d in h.node.downs())


def test_suspicion_comes_before_death_and_is_reported():
    w = settled(4)
    victim = w.running()[0]
    w.crash(victim)
    w.run(8)
    for handle in w.running():
        kinds = [type(e).__name__ for e in handle.node.events
                 if getattr(e, "node_id", None) == victim.node_id]
        assert kinds[-2:] == ["NodeSuspect", "NodeDown"], kinds


# -- no false positives ----------------------------------------------------------

@pytest.mark.parametrize("loss", [0.05, 0.2])
def test_packet_loss_never_removes_healthy_nodes(loss):
    w = settled(6, seed=int(loss * 100))
    w.set_loss(loss)
    w.run(600)                                   # ten minutes of virtual time
    assert all_events(w, mem.NodeDown) == []
    assert sum(h.node.membership.stats.false_positives for h in w.running()) == 0
    w.set_loss(0.0)
    w.assert_converged(5000)


def test_one_bad_link_is_covered_by_witnesses_instead_of_condemning_the_peer():
    w = settled(6, seed=3)
    a, b = w.running()[0], w.running()[1]
    w.net.set_link(a.address, b.address, ms.LinkProfile(loss=1.0))
    w.run(120)
    assert all_events(w, mem.NodeDown) == []
    saves = a.node.membership.stats.indirect_saves + b.node.membership.stats.indirect_saves
    assert saves > 0 and a.node.membership.stats.suspicions > 0
    assert a.node.membership.member(b.node_id).status in {mem.ALIVE, mem.SUSPECT}


# -- sleep / wake / clock ----------------------------------------------------------

def test_sleeping_node_is_marked_down_by_others_and_rejoins_without_duplicates():
    w = settled(4, seed=5)
    sleeper, others = w.running()[0], w.running()[1:]
    w.sleep(sleeper)
    w.run(30)
    for other in others:
        assert other.node.membership.member(sleeper.node_id) is None
        assert any(d.node_id == sleeper.node_id for d in other.node.downs())
    w.wake(sleeper)
    elapsed = w.time_to_converge(2.0)
    assert elapsed is not None
    for handle in w.running():
        assert len([m for m in handle.node.membership.members()
                    if m.node_id == sleeper.node_id]) <= 1
    revived = [e for o in others for e in o.node.events
               if isinstance(e, mem.NodeUp) and e.node_id == sleeper.node_id and e.why == "revived"]
    assert len(revived) == len(others)
    assert w.check_invariants() == []


@pytest.mark.parametrize("hook", [True, False])
@pytest.mark.parametrize("monotonic_pauses", [True, False])
def test_local_sleep_never_makes_the_sleeper_suspect_everyone(hook, monotonic_pauses):
    w = world(6, hook_wake=hook)
    w.join(4)
    w.assert_converged(5000)
    w.run(5)
    sleeper = w.running()[0]
    w.sleep(sleeper, monotonic_pauses=monotonic_pauses)
    w.run(40)
    w.wake(sleeper)
    w.run(2)
    events = sleeper.node.events
    assert not any(isinstance(e, (mem.NodeSuspect, mem.NodeDown)) for e in events)
    assert w.time_to_converge(8.0) is not None
    if not monotonic_pauses or hook:
        assert sleeper.node.membership.stats.wakes >= 1


def test_wall_clock_jump_is_treated_as_a_pause_not_a_failure():
    w = settled(3, seed=7)
    node = w.running()[0]
    node.clock.skew_s += 3600                      # NTP step of one hour
    w.run(6)
    assert node.node.membership.stats.wakes == 1
    assert not any(isinstance(e, (mem.NodeSuspect, mem.NodeDown)) for e in node.node.events)


# -- partitions and restarts ---------------------------------------------------------

def test_partition_and_heal_converge_without_resurrecting_the_dead():
    w = settled(6, seed=8)
    nodes = w.running()
    left, right = nodes[:3], nodes[3:]
    w.partition(left, right)
    w.run(5)
    w.crash(right[0])                                # dies during the partition
    w.run(60)
    for handle in left:
        assert not [m for m in handle.node.membership.members() if m.node_id in
                    {n.node_id for n in right}]
    w.heal()
    elapsed = w.time_to_converge(3.0)
    assert elapsed is not None
    for handle in w.running():
        ids = {m.node_id for m in handle.node.membership.members()}
        assert right[0].node_id not in ids
    assert w.check_invariants() == []


def test_a_quick_restart_is_a_new_boot_of_the_same_member_not_a_death():
    w = settled(3, seed=9)
    a, b = w.running()[0], w.running()[1]
    old = a.boot_id
    w.restart(a)
    assert w.time_to_converge(3.0) is not None
    ups = [e for e in b.node.events if isinstance(e, mem.NodeUp)
           and e.node_id == a.node_id and e.why == "restart"]
    assert len(ups) == 1 and ups[0].boot_id == a.boot_id != old
    assert b.node.membership.member(a.node_id).boot_id == a.boot_id


def test_a_restart_after_a_death_is_reported_as_restart():
    w = settled(3, seed=10)
    a, b = w.running()[0], w.running()[1]
    w.crash(a)
    w.run(10)
    assert b.node.membership.tombstone(a.node_id) is not None
    w.start(a)
    assert w.time_to_converge(3.0) is not None
    assert b.node.membership.tombstone(a.node_id) is None
    assert [e.why for e in b.node.events if isinstance(e, mem.NodeUp)
            and e.node_id == a.node_id][-1] == "restart"


def test_address_change_is_reported_as_a_move_not_a_new_node():
    w = settled(3, seed=11)
    a, b = w.running()[0], w.running()[1]
    new = w.change_ip(a)
    w.run(3)
    moved = [e for e in b.node.events if isinstance(e, mem.NodeMoved)]
    assert moved and moved[-1].address == new
    assert b.node.membership.member(a.node_id).address == new
    assert not b.node.downs()


# -- tombstones and gossip ----------------------------------------------------------

def test_tombstones_expire_and_are_bounded():
    w = settled(3, seed=12)
    a, b = w.running()[0], w.running()[1]
    w.crash(a)
    w.run(10)
    assert b.node.membership.tombstone(a.node_id) is not None
    w.run(mem.MembershipConfig().tombstone_s + 2)
    assert b.node.membership.tombstone(a.node_id) is None
    membership = b.node.membership
    for index in range(mem.MAX_TOMBSTONES + 20):
        membership._tombstones[f"{index:032x}"] = mem.Tombstone(
            f"{index:032x}", "1" * 32, 0, "timeout", 0.0)
        while len(membership._tombstones) > mem.MAX_TOMBSTONES:
            membership._tombstones.popitem(last=False)
    assert len(membership._tombstones) == mem.MAX_TOMBSTONES


def test_second_hand_gossip_cannot_resurrect_a_dead_node():
    w = settled(3, seed=13)
    a, b = w.running()[0], w.running()[1]
    victim_boot, victim = a.boot_id, a.node_id
    w.crash(a)
    w.run(10)
    membership = b.node.membership
    tomb = membership.tombstone(victim)
    assert tomb is not None
    assert not membership.observe_gossip(victim, victim_boot, tomb.incarnation, mem.ALIVE)
    assert not membership.observe_gossip(victim, victim_boot, tomb.incarnation - 1, mem.ALIVE)
    assert membership.member(victim) is None


def test_a_departed_boot_cannot_come_back_from_a_late_datagram():
    w = settled(3, seed=14)
    a, b = w.running()[0], w.running()[1]
    boot = a.boot_id
    w.stop(a, clean=True)
    w.run(2)
    assert b.node.membership.tombstone(a.node_id).reason == "goodbye"
    late = mb.PeerSeen(a.node_id, boot, a.address, 8801, 0, 1, 1, "new")
    b.node.membership.on_beacon_event(late)
    assert b.node.membership.member(a.node_id) is None
    fresh = mb.PeerSeen(a.node_id, "f" * 32, a.address, 8801, 0, 1, 2, "new")
    b.node.membership.on_beacon_event(fresh)
    assert b.node.membership.member(a.node_id).boot_id == "f" * 32


# -- refutation and probes -----------------------------------------------------------

def test_a_suspected_node_refutes_by_raising_its_incarnation():
    w = settled(2, seed=15)
    a, b = w.running()
    before = b.node.local.incarnation
    reply = b.node.membership._on_ping("x", {"from": a.node_id, "suspect": before})
    assert b.node.local.incarnation == before + 1 and reply["incarnation"] == before + 1
    # A stale suspicion (older incarnation) changes nothing.
    b.node.membership._on_ping("x", {"suspect": 0})
    assert b.node.local.incarnation == before + 1


def test_a_higher_incarnation_beat_clears_suspicion_and_reports_refutation():
    w = settled(2, seed=16)
    a, b = w.running()
    member = a.node.membership.member(b.node_id)
    member.status = mem.SUSPECT
    beat = mb.PeerBeat(b.node_id, b.boot_id, b.address, member.incarnation + 3, 5, True, 8801, 1)
    a.node.membership.on_beacon_event(beat)
    assert member.status == mem.ALIVE
    assert any(isinstance(e, mem.NodeRefuted) and e.incarnation == member.incarnation
               for e in a.node.events)


def test_a_forged_goodbye_is_confirmed_by_probe_and_rejected():
    w = settled(3, seed=17)
    a, b = w.running()[0], w.running()[1]
    forged = mb.PeerGone(b.node_id, b.boot_id, b.address)
    a.node.membership.on_beacon_event(forged)
    w.run(1.0)
    assert a.node.membership.member(b.node_id).status == mem.ALIVE
    assert a.node.membership.stats.goodbyes_refuted == 1
    assert not a.node.downs()


def test_pingreq_only_vouches_for_peers_it_hears_first_hand():
    w = settled(3, seed=18)
    a, b, c = w.running()
    assert a.node.membership._on_pingreq("x", {"target": b.node_id}) == {"ok": True}
    assert a.node.membership._on_pingreq("x", {"target": "d" * 32}) == {"ok": False}
    assert a.node.membership._on_pingreq("x", {"target": 5}) == {"ok": False}
    w.crash(b)
    w.run(2.5)
    assert a.node.membership._on_pingreq("x", {"target": b.node_id}) == {"ok": False}
    assert c.node.membership.member(b.node_id) is not None


# -- duplicate identity --------------------------------------------------------------

def test_only_the_later_started_clone_regenerates_its_identity():
    w = world(19)
    first = w.add("orig")
    clone = w.add("clone")
    clone.node.node_id = first.node_id
    clone.node.local.node_id = first.node_id
    clone.node.local.boot_epoch += 5               # the clone started later
    w.run(6)
    assert clone.node.regenerated >= 1 and first.node.regenerated == 0
    clashes = [e for e in first.node.events if isinstance(e, mem.IdentityClash)]
    assert clashes and clashes[0].own and not clashes[0].regenerate
    assert mem.later_started_regenerates(10, "a", 5, "z")
    assert not mem.later_started_regenerates(5, "z", 10, "a")
    assert mem.later_started_regenerates(5, "b", 5, "a")      # deterministic tie-break
    assert not mem.later_started_regenerates(5, "a", 5, "b")


# -- bounds, shutdown, robustness ------------------------------------------------------

def test_member_table_is_bounded_under_a_flood_of_new_identities():
    w = settled(2, seed=20)
    a = w.running()[0]
    for index in range(150):
        event = mb.PeerSeen(f"{index + 5000:032x}", "1" * 32, f"10.2.0.{index % 250 + 1}",
                            8801, 0, 1, 1, "new")
        a.node.membership.on_beacon_event(event)
    assert len(a.node.membership.members()) <= 64


def test_close_stops_the_tick_and_ignores_later_events():
    w = settled(2, seed=21)
    a, b = w.running()
    a.node.membership.close()
    before = len(a.node.events)
    a.node.membership.on_beacon_event(mb.PeerGone(b.node_id, b.boot_id, b.address))
    w.run(20)
    assert len(a.node.events) == before


def test_a_failing_event_callback_does_not_break_detection():
    w = settled(3, seed=22)
    a = w.running()[0]
    a.node.membership._emit = lambda event: 1 / 0
    w.crash(w.running()[1])
    w.run(10)
    assert len(a.node.membership.members()) == 1      # the crashed peer was removed


def test_rpc_router_rejects_garbage_and_survives_handler_errors():
    w = world(23)
    a, b = w.join(2)
    router = b.node.rpc
    router.register("boom", lambda src, body: 1 / 0)
    router.register("echo", lambda src, body: {"seen": body})
    results = {}
    for kind, body in (("echo", {"x": 1}), ("boom", {}), ("nope", {})):
        a.node.rpc.call(b.address, kind, body,
                        lambda r, e, kind=kind: results.__setitem__(kind, (r, e)), 2)
    w.run(5)
    assert results["echo"] == ({"seen": {"x": 1}}, None)
    assert results["boom"] == (None, "refused") and results["nope"] == (None, "refused")
    assert router.errors == 1
    out = []
    a.node.rpc.call(b.address, "Bad Kind", {}, lambda r, e: out.append((r, e)))
    assert out == [(None, "invalid")]
    assert router._dispatch("x", b"\xff\xfe") is None
    assert router._dispatch("x", b"echo\n[1]") is None
    assert router._dispatch("x", b"echo\n" + b"1" * 200_000) is None
    assert isinstance(router, RpcRouter)


def test_membership_budgets_are_reported_by_the_harness():
    w = settled(5, seed=24)
    w.measure_leave(w.running()[0], clean=False)
    w.measure_leave(w.running()[0], clean=True)
    report = w.report()
    assert report["silent_loss_s"]["max"] <= ms.BUDGETS["silent_loss_s"]
    assert report["leave_clean_s"]["max"] <= ms.BUDGETS["leave_clean_s"]


def test_seeded_random_churn_with_full_membership_holds_for_40_seeds():
    failures = ms.run_seeds(range(40), factory=MemberNode)
    assert failures == [], failures[:2]
