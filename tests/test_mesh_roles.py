"""Primary media node succession (#399)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_roles as roles
import mesh_sim as ms
from mesh_full_node import FullNode

C = roles.Candidate


def test_pure_choice_is_minimum_epoch_then_id_and_ignores_input_order():
    nodes = [C("b" * 32, 10, 99), C("a" * 32, 10, 99), C("c" * 32, 5, 99)]
    assert roles.choose_primary(nodes, None) == "c" * 32
    assert roles.choose_primary(reversed(nodes), None) == "c" * 32
    tie = [C("b" * 32, 7, 99), C("a" * 32, 7, 99)]
    assert roles.choose_primary(tie, None) == "a" * 32
    assert roles.choose_primary([], None) is None
    assert roles.choose_primary([C("x" * 32, 1, 0)], None) == "x" * 32


def test_hysteresis_blocks_a_fresh_older_node_until_it_has_been_alive_long_enough():
    me, old = C("b" * 32, 10, 99), C("a" * 32, 1, 2.0)
    assert roles.choose_primary([me, old], "b" * 32, 5.0) == "b" * 32
    old = C("a" * 32, 1, 5.0)
    assert roles.choose_primary([me, old], "b" * 32, 5.0) == "a" * 32     # older wins on merge


def test_a_suspect_primary_keeps_the_role_but_a_suspect_never_gains_it():
    cur = C("b" * 32, 5, 99, suspect=True)
    other = C("c" * 32, 9, 99)
    assert roles.choose_primary([cur, other], "b" * 32) == "b" * 32
    assert roles.choose_primary([cur, other], None) == "c" * 32
    assert roles.choose_primary([cur], None) == "b" * 32


def test_when_nobody_is_eligible_yet_the_oldest_still_leads():
    nodes = [C("b" * 32, 9, 1.0), C("a" * 32, 9, 0.5)]
    assert roles.choose_primary(nodes, None, 5.0) == "a" * 32


class PrimaryNode(FullNode):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.changed = []
        self.skew = kw["clock"].wall() - kw["clock"].monotonic()
        self.tracker = roles.PrimaryTracker(
            clock=kw["clock"], own_id=kw["node_id"], own_epoch=kw["boot_epoch"],
            members=lambda: [(m.node_id, m.boot_id, m.boot_epoch, m.status == "suspect")
                             for m in self.membership.members()],
            on_change=self.changed.append)

    def start(self):
        super().start()
        self.tracker.start()

    def stop(self, clean):
        self.tracker.close()
        super().stop(clean)


def primaries(w):
    return {h.node.tracker.primary for h in w.running()}


def world(seed=1, **kw):
    return ms.SimWorld(seed, PrimaryNode, **kw)


def test_the_first_node_up_is_primary_and_everyone_agrees():
    w = world(1)
    first = w.add()
    w.run(1)
    assert first.node.tracker.is_primary and first.node.changed[0].reason == "first"
    w.run(10)
    for _ in range(5):
        w.add()
        w.run(2)
    w.run(10)
    assert primaries(w) == {first.node_id}
    assert sum(h.node.tracker.is_primary for h in w.running()) == 1


def test_handover_when_the_primary_crashes_or_leaves_is_fast_and_silent():
    for clean, budget in ((False, 8.0), (True, 6.0)):
        w = world(2)
        nodes = w.join(5)
        w.run(15)
        lead = next(h for h in nodes if h.node.tracker.is_primary)
        expected = min((h for h in nodes if h is not lead),
                       key=lambda h: (h.node.local.boot_epoch, h.node_id)).node_id
        elapsed = w.measure_leave(lead, clean=clean)
        got = w.run_until(lambda: primaries(w) == {expected}, budget)
        assert got is not None and elapsed + got < budget + 1
        assert w.converged()


def test_losing_the_primary_changes_nothing_but_the_label():
    w = world(3)
    nodes = w.join(4)
    w.run(15)
    other = next(h for h in nodes if not h.node.tracker.is_primary)
    w.add_target(other, "mine")
    lead = next(h for h in nodes if h.node.tracker.is_primary)
    w.crash(lead)
    w.run(12)
    assert "mine" in other.node.target_ids() and w.converged()


def test_two_meshes_merging_adopt_the_older_primary():
    w = world(4)
    a = w.join(3)
    w.run(2)
    w.partition(a[:1], a[1:])
    w.run(20)
    assert len(primaries(w)) == 2
    w.heal()
    assert w.run_until(lambda: len(primaries(w)) == 1, 15.0) is not None
    assert primaries(w) == {min(a, key=lambda h: (h.node.local.boot_epoch, h.node_id)).node_id}


def test_no_flapping_under_heavy_packet_loss():
    w = world(5)
    w.join(6)
    w.run(15)
    w.set_loss(0.2)
    before = sum(h.node.tracker.changes for h in w.running())
    w.run(1800)
    assert sum(h.node.tracker.changes for h in w.running()) - before == 0


@pytest.mark.parametrize("skew_days", [-1, 1])
def test_clock_skew_changes_who_is_first_but_never_agreement(skew_days):
    w = world(6)
    handles = []
    for index in range(5):
        h = w.add(start=False, skew_s=skew_days * 86400 * (index % 2))
        handles.append(h)
    for h in handles:
        w.start(h)
        w.run(1)
    w.run(20)
    assert len(primaries(w)) == 1 and w.converged()


def test_agreement_holds_across_seeded_random_churn_for_60_seeds():
    for seed in range(60):
        w = world(seed)
        ms.random_scenario(w)
        assert w.converged(), seed
        w.run(8)
        live = {h.node_id for h in w.running()}
        assert len(primaries(w)) == 1 and primaries(w) <= live, (seed, primaries(w))
