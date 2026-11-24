"""Cross-node acquisition observation: no GUI, external downloads or mutations."""
from __future__ import annotations

from types import SimpleNamespace as NS

import mesh_acquisition_activity as activity
import mesh_membership as membership
import peer_protocol as protocol
import pytest

from test_mesh_service import make, link, wait_for


A, B = "a" * 32, "b" * 32
BOOT_A, BOOT_B = "c" * 32, "d" * 32
JOB = "e" * 24


def job(**changes):
    return {"id": JOB, "kind": "magnet", "stage": "downloading",
            "received": 1024, "total": 4096, "rate": 512,
            "title": "private title", "url": "magnet:private", "owner": "private",
            **changes}


class Clock:
    now = 10.0

    def monotonic(self):
        return self.now

    def call_later(self, seconds, callback):
        return NS(cancel=lambda: None)


class Rpc:
    def __init__(self):
        self.pending = []

    def register(self, kind, handler, *, protected):
        assert kind == activity.RPC_KIND and protected
        self.handler = handler

    def call(self, endpoint, kind, body, callback, timeout):
        self.pending.append((endpoint, kind, body, callback))


def rig():
    clock = Clock()
    rpc = Rpc()
    own = NS(node_id=A, boot_id=BOOT_A)
    peer = NS(node_id=B, boot_id=BOOT_B, address="192.168.1.4",
              endpoint="192.168.1.4:9000", status=membership.ALIVE)
    record = NS(boot_id=BOOT_B, name="Kitchen", capabilities=(activity.HINT,))
    peers = [peer]
    disabled = set()
    service = activity.AcquisitionActivity(
        clock=clock, rpc=rpc, members=lambda: peers,
        record=lambda node: record if node == B else None,
        own=lambda: own, version="1.2.0", local_jobs=lambda: [job()],
        disabled=lambda node: frozenset(disabled))
    return service, clock, rpc, peers, record, disabled


def test_source_and_boot_bound_read_only_handshake():
    service, _, rpc, peers, _, disabled = rig()
    body = {"node": B, "boot": BOOT_B, "target": A, "target_boot": BOOT_A,
            "hello": protocol.local_handshake("1.2.0", (activity.CAPABILITY,)).wire()}
    assert rpc.handler("192.168.1.5", body) is None
    assert rpc.handler(peers[0].address, {**body, "boot": "f" * 32}) is None
    assert rpc.handler(peers[0].address, {**body, "target_boot": "f" * 32}) is None
    assert rpc.handler(peers[0].address, {**body, "hello": None}) is None
    assert rpc.handler(peers[0].address, {
        **body, "hello": protocol.local_handshake("1.2.0").wire()}) is None
    result = rpc.handler(peers[0].address, body)
    assert result["jobs"] == [{"id": JOB, "kind": "magnet", "stage": "downloading",
                               "received": 1024, "total": 4096, "rate": 512}]
    disabled.add(activity.CAPABILITY)
    assert rpc.handler(peers[0].address, body) is None
    disabled.clear()
    peers[0].status = membership.SUSPECT
    assert rpc.handler(peers[0].address, body) is None


def test_progress_is_fenced_to_current_peer_and_stale_is_not_live():
    service, clock, rpc, peers, record, _ = rig()
    service.start()
    assert service.snapshot()["nodes"][0]["freshness"] == "waiting"
    cb = rpc.pending.pop()[3]
    reply = {"node": B, "boot": BOOT_B, "hello": service.hello.wire(), "jobs": [job()]}
    cb(reply, None)
    snapshot = service.snapshot()
    assert snapshot["nodes"][0]["freshness"] == "live"
    assert snapshot["nodes"][0]["jobs"][0]["received"] == 1024
    assert "private" not in str(snapshot)
    snapshot["nodes"].clear()
    assert service.snapshot()["nodes"]
    prior_revision = service.revision()
    clock.now += activity.REPEAT_SECONDS
    service._tick()
    cb = rpc.pending.pop()[3]
    cb(None, "timeout")
    assert service.snapshot()["nodes"][0]["freshness"] == "stale"
    assert service.revision() > prior_revision
    clock.now += 6
    service._tick()
    old_cb = rpc.pending.pop()[3]
    peers[0].boot_id = record.boot_id = "f" * 32
    service._tick()
    old_cb(reply, None)
    new = service.snapshot()["nodes"][0]
    assert new["freshness"] == "waiting" and new["jobs"] == []
    peers.clear()
    service._tick()
    assert service.snapshot()["nodes"] == []
    service.close()
    assert service.snapshot()["available"] is False


def test_invalid_remote_rows_and_measurements_are_bounded():
    with pytest.raises(ValueError):
        activity.clean_jobs([job(id="file:///secret")], strict=True)
    with pytest.raises(ValueError):
        activity.clean_jobs([job(stage="private")], strict=True)
    with pytest.raises(ValueError):
        activity.clean_jobs([job()] * 5, strict=True)
    assert activity.clean_jobs([job(received=True, total=-2, rate=10**20)],
                               strict=True)[0] == {
        "id": JOB, "kind": "magnet", "stage": "downloading",
        "received": None, "total": None, "rate": None}
    assert activity.clean_jobs([job(received=5000)])[0]["total"] is None
    assert activity.clean_jobs([job(stage="ready")]) == []


def test_unadvertised_peer_and_late_callback_do_not_create_observations():
    service, _, rpc, _, record, _ = rig()
    record.capabilities = ()
    service.start()
    assert not rpc.pending
    assert service.snapshot()["nodes"] == []
    record.capabilities = (activity.HINT,)
    service._tick()
    callback = rpc.pending.pop()[3]
    service.close()
    callback({"node": B, "boot": BOOT_B, "hello": service.hello.wire(),
              "jobs": [job()]}, None)
    assert service.snapshot()["nodes"] == []


def test_two_real_loopback_nodes_report_live_acquisition_and_departure(tmp_path):
    rows = [job()]
    a = make(tmp_path, "alpha", link_activity=lambda: list(rows))
    b = make(tmp_path, "beta")
    try:
        assert a.start() and b.start()
        link(a, b)

        def observed():
            nodes = b.acquisition_activity.snapshot()["nodes"]
            return next((node for node in nodes if node["node"] == a.node_id), {})

        assert wait_for(lambda: observed().get("freshness") == "live", timeout=12)
        assert observed()["jobs"][0]["received"] == 1024
        assert "private" not in str(observed())
        rows[:] = [job(received=3072)]
        assert wait_for(lambda: observed().get("jobs", [{}])[0].get("received") == 3072,
                        timeout=8)
        rows.clear()
        assert wait_for(lambda: observed().get("jobs") == [], timeout=8)
        a.stop()
        assert wait_for(lambda: not observed(), timeout=12)
    finally:
        a.stop()
        b.stop()
