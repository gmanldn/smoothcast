"""#589: assignment, fencing and exactly-once rules; pure, no network/GUI."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_acquisition_assignment as ma
from mesh_acquisition_assignment import (AssignmentLedger, ExecutorGuard, LedgerError, NodeOffer,
                                         select_executor)

KEY = ma.source_key("youtube", "abcdefghijk")
KEY2 = ma.source_key("magnet", "a" * 40)
CONTENT = "c" * 64
JOB = "job-00000001"


def offer(node, **kw):
    base = dict(trusted=True, live=True, opted_in=True, protocol=1, providers=frozenset({"youtube", "magnet"}),
                free_bytes=50 << 30, slots_free=1)
    return NodeOffer(node, **{**base, **kw})


# -- selection -----------------------------------------------------------------
def test_prefers_local_then_most_free_space_deterministically():
    offers = [offer("b", free_bytes=90 << 30), offer("a", free_bytes=90 << 30), offer("me", local=True, free_bytes=10 << 30)]
    assert select_executor("youtube", 1 << 20, offers).node_id == "me"
    sel = select_executor("youtube", 1 << 20, offers, prefer_local=False)
    assert (sel.node_id, sel.local) == ("a", False)  # tie on space -> node id
    assert select_executor("youtube", 1 << 20, reversed(offers), prefer_local=False).node_id == "a"


@pytest.mark.parametrize("field", [dict(trusted=False), dict(live=False), dict(opted_in=False), dict(protocol=0),
                                   dict(providers=frozenset({"magnet"})), dict(slots_free=0),
                                   dict(free_bytes=1 << 20)])
def test_ineligible_nodes_are_never_selected(field):
    assert select_executor("youtube", 1 << 20, [offer("peer", **field)]) is None


def test_fallback_to_remote_when_local_cannot_and_none_when_nobody_can():
    local = offer("me", local=True, slots_free=0)
    assert select_executor("youtube", 1, [local, offer("far")]).node_id == "far"
    assert select_executor("youtube", 1, [local]) is None
    assert select_executor("youtube", "huge", [offer("far")]) is None  # junk size never fits
    assert select_executor("youtube", 1, [offer("bad id!")]) is None


def test_local_node_needs_no_protocol_but_remote_does():
    assert select_executor("youtube", 1, [offer("me", local=True, protocol=0)]).local
    assert ma.negotiate(1, 1) == 1 and ma.negotiate(3, 2) == 2
    for junk in (0, None, "1", -1, 1.5):
        assert ma.negotiate(1, junk) == 0


# -- ledger lifecycle ------------------------------------------------------------
def started(now=0.0):
    ledger = AssignmentLedger(lease_seconds=60, stale_seconds=30)
    assert ledger.create(JOB, KEY, now) == JOB
    node, gen = ledger.assign(JOB, "n1", now)
    return ledger, node, gen


def test_happy_path_enqueues_exactly_once():
    ledger, node, gen = started()
    for stage in ("metadata", "downloading", "verifying"):
        ledger.report(JOB, node, gen, stage, 1.0, received=5, total=10)
    ledger.finished(JOB, node, gen, CONTENT, 2.0)
    with pytest.raises(LedgerError, match="match"):
        ledger.enqueue_once(JOB, "d" * 64)  # corrupted transfer is never queued
    assert ledger.enqueue_once(JOB, CONTENT) is True
    assert ledger.enqueue_once(JOB, CONTENT) is False  # replay
    assert ledger.jobs[JOB].state == "queued"


def test_duplicate_submissions_share_one_download_until_terminal():
    ledger = AssignmentLedger()
    first = ledger.create(JOB, KEY, 0)
    assert ledger.create("job-00000002", KEY, 1) == first
    assert ledger.create("job-00000003", KEY2, 1) == "job-00000003"
    ledger.cancel(JOB)
    assert ledger.create("job-00000004", KEY, 2) == "job-00000004"  # may be retried after it ended


def test_progress_never_regresses_and_numbers_are_bounded():
    ledger, node, gen = started()
    ledger.report(JOB, node, gen, "downloading", 1, received=8, total=10)
    ledger.report(JOB, node, gen, "metadata", 2, received=2, total=10)  # late/replayed
    job = ledger.jobs[JOB]
    assert (job.state, job.received) == ("downloading", 8)
    ledger.report(JOB, node, gen, "downloading", 3, received=10**30, total=10)
    assert job.received <= job.total
    ledger.report(JOB, node, gen, "downloading", 4, received=-5, total="x")
    assert job.total == 0 and job.received >= 0
    with pytest.raises(LedgerError):
        ledger.report(JOB, node, gen, "queued", 5)  # executors cannot claim queue acceptance


# -- fencing, ambiguity, recovery ------------------------------------------------
def test_expired_lease_is_ambiguous_and_never_silently_reassigned():
    ledger, node, gen = started()
    assert ledger.tick(30) == [] and ledger.tick(61) == [JOB]
    with pytest.raises(LedgerError, match="assignable"):
        ledger.assign(JOB, "n2", 62)
    with pytest.raises(LedgerError, match="unresolved"):
        ledger.resolve_ambiguous(JOB, executor_confirmed_stopped=False)
    with pytest.raises(LedgerError, match="stale fence"):
        ledger.report(JOB, node, gen, "downloading", 62)  # even the old owner must re-handshake
    assert ledger.resolve_ambiguous(JOB, executor_confirmed_stopped=True) == gen
    node2, gen2 = ledger.assign(JOB, "n2", 70)
    assert gen2 == gen + 1
    with pytest.raises(LedgerError, match="stale fence"):
        ledger.report(JOB, node, gen, "downloading", 71)  # zombie from generation 1
    with pytest.raises(LedgerError, match="stale fence"):
        ledger.finished(JOB, node, gen, CONTENT, 72)
    ledger.report(JOB, node2, gen2, "downloading", 72)


def test_duplicate_risk_can_be_accepted_explicitly():
    ledger, *_ = started()
    ledger.tick(100)
    ledger.resolve_ambiguous(JOB, executor_confirmed_stopped=False, accept_duplicate_risk=True)
    assert ledger.assign(JOB, "n2", 101)[1] == 2


def test_heartbeat_extends_the_lease():
    ledger, node, gen = started()
    ledger.report(JOB, node, gen, "downloading", 50)
    assert ledger.tick(100) == []  # renewed at 50 -> valid to 110
    assert ledger.tick(111) == [JOB]


def test_cancel_propagates_target_and_blocks_late_results():
    ledger, node, gen = started()
    assert ledger.cancel(JOB) == (node, gen)
    assert ledger.cancel(JOB) is None
    with pytest.raises(LedgerError, match="finished"):
        ledger.finished(JOB, node, gen, CONTENT, 5)
    assert ledger.enqueue_once(JOB, CONTENT) is False
    pending = AssignmentLedger()
    pending.create(JOB, KEY, 0)
    assert pending.cancel(JOB) is None  # nothing was running anywhere


def test_failure_is_fenced_and_terminal():
    ledger, node, gen = started()
    with pytest.raises(LedgerError):
        ledger.fail(JOB, "other", gen)
    ledger.fail(JOB, node, gen)
    assert ledger.jobs[JOB].state == "failed"


def test_restart_marks_running_jobs_ambiguous_and_survives_json_roundtrip():
    ledger, node, gen = started()
    ledger.report(JOB, node, gen, "downloading", 1, received=3, total=9)
    ledger.create("job-00000002", KEY2, 1)  # still pending
    restored = AssignmentLedger.restore(json.loads(json.dumps(ledger.snapshot())))
    assert restored.jobs[JOB].ambiguous and restored.jobs[JOB].generation == gen
    assert not restored.jobs["job-00000002"].ambiguous
    with pytest.raises(LedgerError, match="assignable"):
        restored.assign(JOB, "n2", 5)  # no double download after a reboot
    restored.resolve_ambiguous(JOB, executor_confirmed_stopped=True)
    assert restored.assign(JOB, "n2", 6)[1] == gen + 1
    # a completed enqueue is remembered: replay after restart cannot enqueue twice
    ledger.finished(JOB, node, gen, CONTENT, 2)
    assert ledger.enqueue_once(JOB, CONTENT)
    again = AssignmentLedger.restore(json.loads(json.dumps(ledger.snapshot())))
    assert again.enqueue_once(JOB, CONTENT) is False


@pytest.mark.parametrize("bad", [None, [], {"v": 2, "jobs": []}, {"v": 1, "jobs": "x"},
                                 {"v": 1, "jobs": [{"job_id": "x"}]},
                                 {"v": 1, "jobs": [{"job_id": JOB, "key": "nope"}]},
                                 {"v": 1, "jobs": [{"job_id": JOB, "key": KEY, "state": "weird"}]},
                                 {"v": 1, "jobs": [{"job_id": JOB, "key": KEY, "lease_until": float("nan")}]}])
def test_corrupt_snapshots_are_refused(bad):
    with pytest.raises(LedgerError):
        AssignmentLedger.restore(bad)


def test_public_view_is_redacted_and_marks_stale_observations():
    ledger, node, gen = started()
    ledger.report(JOB, node, gen, "downloading", 10, received=1, total=2)
    fresh = ledger.public_view(20)[0]
    assert fresh["stale"] is False and fresh["executor"] == "n1"
    assert ledger.public_view(41)[0]["stale"] is True  # no report for >30s
    text = json.dumps(ledger.public_view(41))
    assert KEY not in text and "abcdefghijk" not in text and CONTENT not in text
    ledger.tick(100)
    assert ledger.public_view(100)[0]["ambiguous"] is True


def test_bounds_and_invalid_identifiers():
    ledger = AssignmentLedger()
    for bad in ("", "short", "x" * 65, "has space!!", None):
        with pytest.raises(LedgerError):
            ledger.create(bad, KEY, 0)
    with pytest.raises(LedgerError):
        ledger.create(JOB, "notahash", 0)
    for i in range(ma.MAX_JOBS):
        ledger.create(f"job-{i:08d}", ma.source_key("m", str(i)), 0)
    with pytest.raises(LedgerError, match="too many"):
        ledger.create("job-overflow", ma.source_key("m", "x"), 0)
    with pytest.raises(LedgerError):
        ledger.create("job-00000000", ma.source_key("m", "y"), 0)  # id reuse
    with pytest.raises(LedgerError, match="unknown"):
        ledger.cancel("job-unknown1")
    with pytest.raises(LedgerError):
        ledger.assign("job-00000001", "bad node!", 0)


# -- executor guard --------------------------------------------------------------
def test_executor_accepts_replays_and_fences_old_generations():
    guard = ExecutorGuard(slots=1)
    assert guard.offer(JOB, 1, KEY) == ("accepted", [])
    assert guard.offer(JOB, 1, KEY) == ("duplicate", [])  # replayed request
    assert guard.offer("job-00000002", 1, KEY2) == ("busy", [])  # no free slot
    assert guard.offer(JOB, 2, KEY) == ("accepted", [JOB])  # supersede: stop gen 1
    assert guard.offer(JOB, 1, KEY) == ("fenced", [])
    assert guard.offer(JOB, 3, KEY2)[0] == "invalid"  # a job id never changes source
    assert guard.done(JOB, 1) is False and guard.done(JOB, 2) is True
    assert guard.offer("job-00000002", 1, KEY2)[0] == "accepted"


def test_executor_cancel_is_fenced_and_blocks_zombie_restart():
    guard = ExecutorGuard(slots=2)
    guard.offer(JOB, 2, KEY)
    assert guard.cancel(JOB, 1) is False  # stale cancel cannot kill the newer run
    assert JOB in guard.running
    assert guard.cancel(JOB, 2) is True
    assert guard.offer(JOB, 2, KEY) == ("fenced", [])  # replayed old assign after cancel
    assert guard.offer(JOB, 3, KEY)[0] == "accepted"


@pytest.mark.parametrize("args", [("bad id", 1, KEY), (JOB, 0, KEY), (JOB, "1", KEY), (JOB, 1, "nope"), (JOB, True, KEY)])
def test_executor_rejects_malformed_offers(args):
    assert ExecutorGuard().offer(*args) == ("invalid", [])


def test_two_node_simulation_failover_without_duplicate_or_double_enqueue():
    ledger = AssignmentLedger(lease_seconds=60)
    guards = {"n1": ExecutorGuard(), "n2": ExecutorGuard()}
    ledger.create(JOB, KEY, 0)
    node, gen = ledger.assign(JOB, "n1", 0)
    assert guards[node].offer(JOB, gen, KEY)[0] == "accepted"
    ledger.tick(100)  # n1 partitioned: ambiguous, not reassigned
    assert ledger.jobs[JOB].ambiguous
    ledger.resolve_ambiguous(JOB, executor_confirmed_stopped=False, accept_duplicate_risk=True)
    node2, gen2 = ledger.assign(JOB, "n2", 101)
    assert guards[node2].offer(JOB, gen2, KEY)[0] == "accepted"
    # n1 heals and still believes it owns generation 1
    with pytest.raises(LedgerError, match="stale fence"):
        ledger.finished(JOB, "n1", gen, CONTENT, 110)
    assert guards["n1"].cancel(JOB, gen2) is True  # fence tells it to stop
    ledger.finished(JOB, node2, gen2, CONTENT, 120)
    assert [ledger.enqueue_once(JOB, CONTENT) for _ in range(3)] == [True, False, False]


def test_completed_executor_generation_cannot_restart_on_delayed_offer():
    guard = ExecutorGuard(slots=1)
    assert guard.offer(JOB, 1, KEY) == ("accepted", [])
    assert guard.done(JOB, 1)
    assert guard.offer(JOB, 1, KEY) == ("fenced", [])
    assert not guard.running
    assert guard.offer(JOB, 2, KEY) == ("accepted", [])


def test_completion_digest_cannot_change_within_one_generation():
    ledger, node, gen = started()
    ledger.finished(JOB, node, gen, CONTENT, 2)
    ledger.finished(JOB, node, gen, CONTENT, 3)  # identical replay is safe
    before = ledger.snapshot()
    with pytest.raises(LedgerError, match="conflicting"):
        ledger.finished(JOB, node, gen, "d" * 64, 4)
    assert ledger.snapshot() == before
    assert ledger.enqueue_once(JOB, CONTENT)


def test_new_generation_can_finish_with_new_content_after_explicit_resolution():
    ledger, node, gen = started()
    ledger.finished(JOB, node, gen, CONTENT, 2)
    ledger.tick(100)
    ledger.resolve_ambiguous(JOB, executor_confirmed_stopped=True)
    node2, gen2 = ledger.assign(JOB, "n2", 101)
    ledger.finished(JOB, node2, gen2, "d" * 64, 102)
    assert ledger.enqueue_once(JOB, "d" * 64)
