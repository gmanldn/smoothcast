"""MeshState acceptance rules, MeshView diffs and bounded subscriptions (#398)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_model as mm
import mesh_sim as sim
import mesh_state as st

ME, A, B = "1" * 32, "a" * 32, "b" * 32
BOOT1, BOOT2 = "c" * 32, "d" * 32


def rec(node=A, boot=BOOT1, rev=1, epoch=100, **kw):
    return mm.NodeRecord(node_id=node, boot_id=boot, name="N", version="1.2.0", rev=rev,
                         boot_epoch=epoch, **kw)


def make(clock=None):
    clock = clock or sim.SimClock()
    return st.MeshState(rec(ME, "e" * 32, 1, 50), clock=clock), clock


def tgt(i):
    return mm.TargetObservation(f"t{i}", "cast", f"TV {i}")


def test_newer_revision_replaces_and_older_or_equal_is_ignored():
    state, _ = make()
    assert state.accept(rec(rev=3), current_boot=BOOT1) is st.Accept.ACCEPTED
    assert state.accept(rec(rev=3), current_boot=BOOT1) is st.Accept.SAME
    assert state.accept(rec(rev=2), current_boot=BOOT1) is st.Accept.STALE
    assert state.accept(rec(rev=4), current_boot=BOOT1) is st.Accept.ACCEPTED
    assert state.get(A).rev == 4


def test_current_boot_from_membership_supersedes_and_other_boots_are_refused():
    state, _ = make()
    state.accept(rec(rev=9), current_boot=BOOT1)
    # membership says the owner now runs BOOT2: its record wins even with a low rev
    assert state.accept(rec(boot=BOOT2, rev=1, epoch=200), current_boot=BOOT2) is st.Accept.ACCEPTED
    assert state.get(A).boot_id == BOOT2
    # a late record of the old boot can never come back
    assert state.accept(rec(boot=BOOT1, rev=99), current_boot=BOOT2) is st.Accept.OLD_BOOT
    assert state.get(A).boot_id == BOOT2


def test_without_membership_knowledge_only_a_later_boot_epoch_may_supersede():
    state, _ = make()
    state.accept(rec(rev=1, epoch=100), current_boot=None)
    assert state.accept(rec(boot=BOOT2, rev=1, epoch=50), current_boot=None) is st.Accept.OLD_BOOT
    assert state.accept(rec(boot=BOOT2, rev=1, epoch=500), current_boot=None) is st.Accept.ACCEPTED


def test_peers_can_never_overwrite_our_own_record():
    state, _ = make()
    forged = rec(ME, "f" * 32, rev=999, epoch=999)
    assert state.accept(forged, current_boot=None) is st.Accept.OWN
    assert state.own.rev == 1 and state.get(ME) is state.own


def test_dropped_boots_are_refused_until_revived_or_expired():
    state, clock = make()
    state.accept(rec(rev=2), current_boot=BOOT1)
    assert state.drop(A) is True and state.get(A) is None
    assert state.accept(rec(rev=5), current_boot=BOOT1) is st.Accept.DEAD
    state.revive(A, BOOT1)
    assert state.accept(rec(rev=5), current_boot=BOOT1) is st.Accept.ACCEPTED
    state.drop(A)
    clock.advance(st.DEAD_BOOT_TTL_S + 1)
    assert state.accept(rec(rev=6), current_boot=BOOT1) is st.Accept.ACCEPTED
    assert state.drop("9" * 32) is False


def test_dead_boot_memory_is_bounded():
    state, _ = make()
    for index in range(st.DEAD_BOOT_MEMORY + 50):
        state.drop(f"{index:032x}", BOOT1)
    assert len(state._dead) == st.DEAD_BOOT_MEMORY


def test_node_count_and_size_caps_refuse_new_nodes_not_established_ones():
    state, _ = make()
    for index in range(mm.MAX_NODES - 1):
        assert state.accept(rec(f"{index + 100:032x}"), current_boot=BOOT1) is st.Accept.ACCEPTED
    assert state.accept(rec("f" * 32), current_boot=BOOT1) is st.Accept.FULL
    assert state.accept(rec(f"{100:032x}", rev=2), current_boot=BOOT1) is st.Accept.ACCEPTED


def test_digest_and_newer_for():
    state, _ = make()
    state.accept(rec(A, rev=3), current_boot=BOOT1)
    state.accept(rec(B, rev=1), current_boot=BOOT1)
    digest = state.digest()
    assert digest[A] == (BOOT1, 3) and ME in digest
    assert state.newer_for(digest) == []
    behind = {A: (BOOT1, 1), B: (BOOT1, 1)}
    assert {r.node_id for r in state.newer_for(behind)} == {A, ME}
    other_boot = {A: (BOOT2, 9)}
    assert A in {r.node_id for r in state.newer_for(other_boot)}      # receiver decides
    assert state.digest_hash() == mm.digest_hash(digest)


def test_set_own_guards_identity_and_monotonic_revisions():
    state, _ = make()
    state.set_own(rec(ME, "e" * 32, 2, 50, targets=(tgt(1),)))
    assert state.own.rev == 2 and state.version > 0
    with pytest.raises(ValueError):
        state.set_own(rec(ME, "e" * 32, 1, 50))
    with pytest.raises(ValueError):
        state.set_own(rec(A, "e" * 32, 3, 50))


# -- view and diff ---------------------------------------------------------------

def view_of(state, alive):
    return st.ViewPublisher(clock=sim.SimClock(), state=state, is_alive=lambda n: n in alive)


def test_view_contains_only_alive_nodes_plus_self_sorted():
    state, _ = make()
    state.accept(rec(A), current_boot=BOOT1)
    state.accept(rec(B), current_boot=BOOT1)
    pub = view_of(state, {B})
    pub.flush()
    assert [n.node_id for n in pub.view.nodes] == [ME, B]
    assert pub.view.node(B) is not None and pub.view.node(A) is None


def test_diff_reports_added_removed_and_sections_changed():
    state, _ = make()
    pub = view_of(state, {A, B})
    state.accept(rec(A, targets=(tgt(1),)), current_boot=BOOT1)
    pub.flush()
    first = pub.view
    state.accept(rec(A, rev=2, targets=(tgt(1), tgt(2)),
                     clients=(mm.ClientSummary("c1", "screen"),)), current_boot=BOOT1)
    state.accept(rec(B), current_boot=BOOT1)
    pub.flush()
    changes = {c.node_id: c for c in st.diff_views(first, pub.view)}
    assert changes[B].kind == "added"
    assert changes[A].kind == "updated" and changes[A].sections == ("targets", "clients")
    state.drop(B)
    pub.flush()
    assert st.diff_views(pub.view, st.MeshView(9, ME, pub.view.nodes[:1]))[0].kind == "removed"
    assert st.diff_views(None, first)[0].kind == "added"


def test_identical_content_publishes_nothing_and_generation_is_monotonic():
    state, clock = make()
    pub = st.ViewPublisher(clock=clock, state=state, is_alive=lambda n: True)
    sub = pub.subscribe()
    sub.poll()
    pub.changed()
    clock.advance(0.2)
    assert pub.publications == 0 and sub.poll() == []
    state.accept(rec(A), current_boot=BOOT1)
    pub.changed()
    pub.changed()
    clock.advance(0.2)
    assert pub.publications == 1 and pub.view.generation == 1
    items = sub.poll()
    assert len(items) == 1 and isinstance(items[0], st.Delta) and items[0].generation == 1


def test_view_fingerprint_is_equal_for_equal_content():
    state1, _ = make()
    state2, _ = make()
    for state in (state1, state2):
        state.accept(rec(A, targets=(tgt(1),)), current_boot=BOOT1)
    p1, p2 = view_of(state1, {A}), view_of(state2, {A})
    p1.flush()
    p2.flush()
    assert p1.view.fingerprint() == p2.view.fingerprint()
    state2.accept(rec(A, rev=2), current_boot=BOOT1)
    p2.flush()
    assert p1.view.fingerprint() != p2.view.fingerprint()
    assert p1.view.targets() == [(A, tgt(1))]


# -- subscriptions -------------------------------------------------------------------

def test_new_subscribers_start_from_a_snapshot_then_get_deltas():
    state, clock = make()
    pub = st.ViewPublisher(clock=clock, state=state, is_alive=lambda n: True)
    ready = []
    sub = pub.subscribe(on_ready=lambda: ready.append(1))
    assert len(ready) == 1
    first = sub.poll()
    assert len(first) == 1 and isinstance(first[0], st.Snapshot)
    state.accept(rec(A), current_boot=BOOT1)
    pub.changed()
    clock.advance(0.2)
    assert len(ready) == 2
    items = sub.poll()
    assert isinstance(items[0], st.Delta) and items[0].changes[0].kind == "added"


def test_a_slow_subscriber_overflows_into_one_consistent_snapshot_with_bounded_memory():
    state, clock = make()
    pub = st.ViewPublisher(clock=clock, state=state, is_alive=lambda n: True)
    slow = pub.subscribe(limit=8)
    fast = pub.subscribe(limit=2000)
    slow.poll()
    fast.poll()
    seen_fast = 0
    for index in range(1000):
        state.accept(rec(A, rev=index + 1, targets=(tgt(index % 7),)), current_boot=BOOT1)
        pub.changed()
        clock.advance(0.06)
        assert slow.pending <= 9
        seen_fast += len(fast.poll())
    assert slow.overflows >= 1 and slow.pending <= 9
    items = slow.poll()
    assert len(items) == 1 and isinstance(items[0], st.Snapshot)
    assert items[0].view is pub.view and items[0].view.node(A).rev == 1000
    assert seen_fast == pub.publications and pub.publications == 1000


def test_subscriber_limits_close_and_callback_errors():
    state, clock = make()
    pub = st.ViewPublisher(clock=clock, state=state, is_alive=lambda n: True,
                           max_subscribers=2)
    bad = pub.subscribe(on_ready=lambda: 1 / 0)         # a failing callback is contained
    other = pub.subscribe()
    with pytest.raises(OverflowError):
        pub.subscribe()
    other.close()
    assert pub.subscriber_count == 1 and other.poll() == []
    pub.subscribe()
    state.accept(rec(A), current_boot=BOOT1)
    pub.changed()
    clock.advance(0.2)
    assert bad.pending >= 1
    pub.close()
    assert pub.subscriber_count == 0
    pub.changed()
    clock.advance(0.2)
