"""Two-node loopback simulation of remote acquisition assignment (#589).

In-process only: a dict-backed 'transport' connects a host and workers; no
sockets, GUI, receiver or real download.
"""
from pathlib import Path
import os
import subprocess
import sys

import mesh_acquisition_assignment as core
import mesh_acquisition_rpc as rpc
import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB = "job-00000001"
URL = "abcdefghijk"  # canonical video id (the only source form that crosses nodes)
CONTENT = "c" * 64


def offer(node, **kw):
    base = dict(node_id=node, trusted=True, live=True, opted_in=True, protocol=1,
                providers=frozenset({"youtube"}), free_bytes=1 << 40, slots_free=1)
    base.update(kw)
    return core.NodeOffer(**base)


class Rig:
    def __init__(self, slots=1):
        self.started, self.stopped, self.down = [], [], False
        self.worker = rpc.WorkerService(lambda *a: self.started.append(a),
                                        lambda j: self.stopped.append(j), slots)
        self.sent = []
        self.host = rpc.HostCoordinator(core.AssignmentLedger(), self.send)

    def send(self, node, msg):
        self.sent.append((node, msg))
        if self.down:
            raise ConnectionError("partition")
        return self.worker.handle(msg)

    def submit(self, job=JOB, **kw):
        return self.host.submit(job, "youtube", URL, [offer("remote-a")], 10, 0.0, **kw)


def test_remote_offer_is_accepted_and_runs_once_under_replay():
    rig = Rig()
    job, sel, outcome = rig.submit()
    assert outcome == "accepted" and sel.node_id == "remote-a" and len(rig.started) == 1
    _, gen = rig.host.ledger.jobs[job].node, rig.host.ledger.jobs[job].generation
    # replayed identical offer (retry/duplicate delivery) must not start a second download
    assert rig.worker.handle(rig.sent[0][1])["verdict"] == "duplicate"
    assert len(rig.started) == 1
    # duplicate submission of the same source joins the live job; nothing re-sent
    job2, _, outcome2 = rig.submit(job="job-00000002")
    assert job2 == job and outcome2 == "duplicate" and len(rig.sent) == 1 and gen == 1


def test_local_node_preferred_without_sending():
    rig = Rig()
    local = offer("me", local=True, protocol=0)
    _, sel, outcome = rig.host.submit(JOB, "youtube", URL, [offer("remote-a"), local], 10, 0.0)
    assert outcome == "local" and sel.local and rig.sent == []


def test_busy_worker_returns_job_to_pending_for_reassignment():
    rig = Rig(slots=0)
    job, _, outcome = rig.submit()
    assert outcome == "refused" and rig.started == []
    row = rig.host.ledger.jobs[job]
    assert row.state == "pending" and row.node is None and not row.ambiguous


def test_partition_is_ambiguous_and_never_silently_reassigned():
    rig = Rig()
    rig.down = True
    job, _, outcome = rig.submit()
    assert outcome == "ambiguous" and rig.host.ledger.jobs[job].ambiguous
    with pytest.raises(core.LedgerError):
        rig.host.ledger.assign(job, "remote-b", 1.0)
    rig.host.ledger.resolve_ambiguous(job, executor_confirmed_stopped=True)
    assert rig.host.ledger.assign(job, "remote-b", 2.0) == ("remote-b", 2)


def test_stale_generation_cannot_report_or_finish_and_sender_is_authenticated():
    rig = Rig()
    job, _, _ = rig.submit()
    report = rpc.build("report", job=job, gen=1, stage="downloading", received=5, total=10)
    assert rig.host.on_message("remote-a", report, 1.0)
    assert not rig.host.on_message("impostor", report, 1.0)
    assert not rig.host.on_message("remote-a", {**report, "gen": 9}, 1.0)
    fin = rpc.build("finished", job=job, gen=1, content=CONTENT)
    assert rig.host.on_message("remote-a", fin, 2.0)
    ledger = rig.host.ledger
    with pytest.raises(core.LedgerError):
        ledger.enqueue_once(job, "d" * 64)  # content mismatch never queues
    assert ledger.enqueue_once(job, CONTENT) is True
    assert ledger.enqueue_once(job, CONTENT) is False  # exactly once


def test_cancel_propagates_and_stale_cancel_is_ignored():
    rig = Rig()
    job, _, _ = rig.submit()
    assert rig.host.cancel(job) is True and rig.stopped == [job]
    assert rig.worker.handle(rpc.build("cancel", job=job, gen=0 + 1))["ok"]
    # an older generation's cancel after a newer offer must not stop the new run
    w = rpc.WorkerService(lambda *a: None, lambda j: rig.stopped.append("x"))
    w.handle(rpc.build("offer", job=JOB, gen=3, key=core.source_key("youtube", URL), kind="youtube", src=URL))
    w.handle(rpc.build("cancel", job=JOB, gen=2))
    assert "x" not in rig.stopped


def test_cancel_with_unreachable_owner_reports_unacknowledged():
    rig = Rig()
    job, _, _ = rig.submit()
    rig.down = True
    assert rig.host.cancel(job) is False


@pytest.mark.parametrize("bad", [
    None, [], {"v": 2, "t": "cancel", "job": JOB, "gen": 1},
    {"v": 1, "t": "cancel", "job": JOB, "gen": 1, "extra": "x"},
    {"v": 1, "t": "cancel", "job": JOB, "gen": 0},
    {"v": 1, "t": "cancel", "job": JOB, "gen": True},
    {"v": 1, "t": "cancel", "job": "x" * 500, "gen": 1},
    {"v": 1, "t": "offer", "job": JOB, "gen": 1, "key": "k" * 64, "kind": "http"},
    {"v": 1, "t": "nope"},
])
def test_malformed_messages_are_refused(bad):
    with pytest.raises(rpc.WireError):
        rpc.parse(bad)
    assert rpc.WorkerService(lambda *a: 1 / 0, lambda j: 1 / 0).handle(bad)["ok"] is False


def test_nothing_sensitive_crosses_the_wire_or_the_public_view():
    rig = Rig()
    rig.submit()
    view = repr(rig.host.ledger.public_view(1.0))
    assert URL not in view and CONTENT not in view  # public/telemetry view: no source, no content key
    wire_blob = repr(rig.sent)
    assert "http" not in wire_blob and "magnet" not in wire_blob  # canonical id only, never a URL


@pytest.mark.parametrize("kind, fields", [
    ("offer", {"job": 123, "key": "a" * 64, "kind": "youtube", "src": "abcdefghijk"}),
    ("offer", {"job": JOB, "key": 123, "kind": "youtube", "src": "abcdefghijk"}),
    ("offer", {"job": JOB, "key": "z" * 64, "kind": "youtube", "src": "abcdefghijk"}),
    ("offer", {"job": JOB, "key": core.source_key("youtube", "abcdefghijk"), "kind": "youtube",
               "src": "https://evil.example/x"}),
    ("offer", {"job": JOB, "key": core.source_key("youtube", "abcdefghijk"), "kind": "youtube",
               "src": "zzzzzzzzzzz"}),  # valid shape but hashes to another key
    ("cancel", {"job": 123}),
    ("cancel", {"job": "../invalid"}),
    ("cancel", {"job": JOB, "gen": 1 << 63}),
    ("finished", {"job": JOB, "content": 123}),
    ("finished", {"job": JOB, "content": "g" * 64}),
    ("report", {"job": JOB, "stage": "downloading", "received": "5", "total": 10}),
    ("report", {"job": JOB, "stage": "downloading", "received": -1, "total": 10}),
    ("report", {"job": JOB, "stage": "downloading", "received": 5, "total": core.MAX_BYTES + 1}),
    ("report", {"job": JOB, "stage": "queued", "received": 5, "total": 10}),
])
def test_acquisition_wire_rejects_invalid_field_schema(kind, fields):
    rig = Rig()
    rig.submit()
    before = rig.host.ledger.snapshot()
    fence = dict(rig.worker.guard.highest)
    cancelled = dict(rig.worker.guard.cancelled)
    running = dict(rig.worker.guard.running)
    message = rpc.build(kind, **{"gen": 1, **fields})
    with pytest.raises(rpc.WireError):
        rpc.parse(message)
    assert not rig.worker.handle(message)["ok"]
    assert not rig.host.on_message("remote-a", message, 100.0)
    assert rig.host.ledger.snapshot() == before
    assert rig.worker.guard.highest == fence
    assert rig.worker.guard.cancelled == cancelled
    assert rig.worker.guard.running == running
    assert len(rig.started) == 1 and not rig.stopped


def test_acquisition_wire_accepts_counter_boundaries():
    for received, total in ((0, 0), (core.MAX_BYTES, core.MAX_BYTES)):
        message = rpc.build("report", job=JOB, gen=1, stage="downloading",
                            received=received, total=total)
        assert rpc.parse(message) == message


def test_acquisition_path_stays_gui_and_receiver_free():
    """Acceptance: assert no GUI or receiver action in CI.

    A fresh ``-I`` interpreter so GTK already imported in this process cannot
    mask a leak: the whole remote-acquisition path must not pull in GTK or a
    receiver controller merely by being imported.
    """
    modules = ["mesh_acquisition_assignment", "mesh_acquisition_rpc",
               "mesh_acquisition_executor", "mesh_acquisition_transfer",
               "mesh_acquisition_store", "mesh_acquisition_activity",
               "mesh_acquisition_bridge", "mesh_acquisition_app", "link_acquisition"]
    code = ("import sys; sys.path.insert(0, %r); import %s; "
            "leaks = sorted(m for m in sys.modules if m == 'gi' or m.startswith('gi.')) "
            "+ [m for m in ('cast_control', 'cast_session', 'dlna') if m in sys.modules]; "
            "assert not leaks, leaks" % (str(ROOT / "src"), ", ".join(modules)))
    env = {"PATH": os.environ.get("PATH", "")}
    result = subprocess.run([sys.executable, "-I", "-c", code],
                            capture_output=True, text=True, timeout=60, env=env)
    assert result.returncode == 0, result.stderr
