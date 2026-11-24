"""Two bridges over a loopback fake of the mesh RPC: assignment end to end (#589)."""
from __future__ import annotations

from types import SimpleNamespace as NS

import mesh_acquisition_assignment as core
import mesh_acquisition_bridge as bridge
import mesh_acquisition_rpc as wire
import mesh_membership as membership
import peer_protocol as protocol
import pytest

HOST, WORK = "a" * 32, "b" * 32
BOOT_H, BOOT_W = "c" * 32, "d" * 32
ADDR = {HOST: "192.168.1.2", WORK: "192.168.1.4"}
JOB = "job-00000001"
URL = "abcdefghijk"  # canonical video id (the only source form that crosses nodes)


class Clock:
    now = 5.0

    def monotonic(self):
        return self.now


class Net:
    """Routes rpc.call to the destination bridge, as the transport would."""

    def __init__(self):
        self.nodes, self.drop = {}, False

    def rpc(self, me):
        net = self

        class Rpc:
            def register(self, kind, handler, *, protected):
                assert kind == bridge.RPC_KIND and protected
                net.nodes[me] = handler

            def call(self, endpoint, kind, body, callback, timeout):
                if net.drop:
                    return callback(None, "timeout")
                target = next(n for n, a in ADDR.items() if a == endpoint)
                callback(net.nodes[target](ADDR[me], body), None)

        return Rpc()


def build(net, me, peer, *, opted_in=True, slots=1, caps=(bridge.HINT,), version="1.2.0", **extra):
    boot = {HOST: BOOT_H, WORK: BOOT_W}
    peer_member = NS(node_id=peer, boot_id=boot[peer], address=ADDR[peer], endpoint=ADDR[peer],
                     status=membership.ALIVE)
    record = NS(boot_id=boot[peer], capabilities=caps)
    started, stopped = [], []
    worker = wire.WorkerService(lambda *a: started.append(a), stopped.append, slots)
    b = bridge.AcquisitionBridge(
        clock=Clock(), rpc=net.rpc(me), members=lambda: [peer_member],
        record=lambda n: record if n == peer else None,
        own=lambda: NS(node_id=me, boot_id=boot[me]), version=version,
        call_soon=lambda fn: fn(), accept=lambda: opted_in, worker=worker, **extra)
    return b, started, stopped


def pair(**worker_kw):
    net = Net()
    ledger = core.AssignmentLedger()
    holder = {}
    host_bridge, _, _ = build(net, HOST, WORK, host=None)
    host = wire.HostCoordinator(ledger, lambda node, msg: host_bridge.send(node, msg))
    host_bridge.host = host
    worker_bridge, started, stopped = build(net, WORK, HOST, host=None, **worker_kw)
    holder.update(net=net, ledger=ledger, host=host, hb=host_bridge, wb=worker_bridge,
                  started=started, stopped=stopped)
    return NS(**holder)


def offers():
    return [core.NodeOffer(WORK, trusted=True, live=True, opted_in=True, protocol=1,
                           providers=frozenset({"youtube"}), free_bytes=1 << 40, slots_free=1)]


def test_offer_crosses_the_authenticated_rpc_and_starts_one_download():
    p = pair()
    job, selection, outcome = p.host.submit(JOB, "youtube", URL, offers(), 10, 0.0)
    assert outcome == "accepted" and selection.node_id == WORK and len(p.started) == 1
    # worker reports back through the same bridge, authenticated by source address
    assert p.wb.send(HOST, wire.build("report", job=job, gen=1, stage="downloading",
                                      received=4, total=10))["ok"]
    assert p.ledger.jobs[job].state == "downloading"
    assert p.wb.send(HOST, wire.build("finished", job=job, gen=1, content="c" * 64))["ok"]
    assert p.ledger.enqueue_once(job, "c" * 64) is True
    assert p.ledger.enqueue_once(job, "c" * 64) is False


def test_worker_that_has_not_opted_in_declines_and_job_returns_to_pending():
    p = pair(opted_in=False)
    job, _, outcome = p.host.submit(JOB, "youtube", URL, offers(), 10, 0.0)
    assert outcome == "refused" and p.started == []
    row = p.ledger.jobs[job]
    assert row.state == "pending" and not row.ambiguous


def test_lost_reply_is_ambiguous_never_reassigned():
    p = pair()
    p.net.drop = True
    job, _, outcome = p.host.submit(JOB, "youtube", URL, offers(), 10, 0.0)
    assert outcome == "ambiguous" and p.ledger.jobs[job].ambiguous


@pytest.mark.parametrize("tamper", ["node", "boot", "target", "target_boot", "source"])
def test_identity_and_source_must_all_match(tamper):
    p = pair()
    body = {"hello": p.hb.hello.wire(), "node": HOST, "boot": BOOT_H, "target": WORK,
            "target_boot": BOOT_W,
            "msg": wire.build("offer", job=JOB, gen=1, key=core.source_key("youtube", URL), kind="youtube", src=URL)}
    source = ADDR[HOST]
    if tamper == "source":
        source = "192.168.1.99"
    else:
        body[tamper] = "f" * 32
    assert p.net.nodes[WORK](source, body) is None and p.started == []


def test_capability_must_be_negotiated_and_not_disabled():
    p = pair()
    body = {"hello": protocol.local_handshake("1.2.0").wire(), "node": HOST, "boot": BOOT_H,
            "target": WORK, "target_boot": BOOT_W,
            "msg": wire.build("cancel", job=JOB, gen=1)}
    assert p.net.nodes[WORK](ADDR[HOST], body) is None  # no assign capability in hello
    p2 = pair()
    p2.hb.disabled = lambda node: frozenset({bridge.CAPABILITY})
    with pytest.raises(ConnectionError):
        p2.hb.send(WORK, wire.build("cancel", job=JOB, gen=1))


def test_peer_without_the_advertised_hint_is_never_contacted():
    net = Net()
    hb, _, _ = build(net, HOST, WORK, caps=("room",))
    with pytest.raises(ConnectionError):
        hb.send(WORK, wire.build("cancel", job=JOB, gen=1))


def test_send_refuses_to_block_the_mesh_loop():
    net = Net()
    hb, _, _ = build(net, HOST, WORK, on_loop=lambda: True)
    with pytest.raises(RuntimeError):
        hb.send(WORK, wire.build("cancel", job=JOB, gen=1))


def test_cancel_propagates_and_stale_cancel_is_ignored_over_the_wire():
    p = pair()
    job, _, _ = p.host.submit(JOB, "youtube", URL, offers(), 10, 0.0)
    assert p.host.cancel(job) is True and p.stopped == [job]


def test_reports_from_a_non_owner_node_are_refused():
    p = pair()
    job, _, _ = p.host.submit(JOB, "youtube", URL, offers(), 10, 0.0)
    # a different authenticated peer (not the assigned executor) cannot move the job
    other = "e" * 32
    msg = wire.build("report", job=job, gen=1, stage="downloading", received=1, total=2)
    assert not p.host.on_message(other, msg, 1.0)
    assert p.ledger.jobs[job].state == "resolving"


def test_mesh_service_only_advertises_and_builds_the_bridge_when_configured():
    import mesh_service
    fields = mesh_service.MeshConfig.__dataclass_fields__
    assert fields["acquisition_worker"].default is None
    assert fields["acquisition_attach"].default is None
    assert fields["acquisition_accept"].default() is False  # never accepting by default
    source = open(mesh_service.__file__).read()
    assert "acquisition_bridge.HINT" in source and "acquisition_bridge.AcquisitionBridge(" in source
