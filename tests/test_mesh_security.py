"""Spoofing, replay, flooding and revocation across the mesh (#404)."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_beacon as mb
import mesh_membership as mem
import mesh_model as mm
import mesh_rpc
import mesh_sim as ms
from mesh_full_node import FullNode
from mesh_ports import Datagram

SRC = Path(__file__).resolve().parents[1] / "src"


def world(seed=1, **kw):
    return ms.SimWorld(seed, FullNode, **kw)


def settled(n, seed=1, **kw):
    w = world(seed, **kw)
    w.join(n)
    w.assert_converged(5000)
    w.run(4)
    return w


def beat(handle, **kw):
    base = dict(kind="heartbeat", node_id=handle.node_id, boot_id=handle.boot_id,
                incarnation=0, rev=1, boot_epoch=handle.node.local.boot_epoch, port=8801,
                nonce="0" * 16)
    base.update(kw)
    return mb.encode(mb.Message(**base))


# -- spoofed identity / endpoint -------------------------------------------------

def test_a_second_source_cannot_hijack_a_live_nodes_endpoint():
    w = settled(3)
    a, b, _c = w.running()
    peer = a.node.beacon.peer(b.node_id)
    for _ in range(20):
        w.run(0.3)
        a.node.beacon._on_datagram(Datagram("192.168.1.250", beat(b), True))
    assert a.node.beacon.peer(b.node_id).address == b.address == peer.address
    assert a.node.beacon.stats.address_conflicts >= 15
    assert w.converged()


def test_a_real_address_change_is_still_accepted_once_the_old_address_is_silent():
    w = settled(3, seed=2)
    a, b, _c = w.running()
    new = w.change_ip(b)
    assert w.run_until(lambda: a.node.beacon.peer(b.node_id).address == new, 5.0) is not None
    assert w.converged()


def test_unsolicited_or_replayed_welcomes_are_ignored():
    w = settled(2, seed=3)
    a, b = w.running()
    before = a.node.beacon.stats.unsolicited_welcomes
    stranger = mb.encode(mb.Message("welcome", "d" * 32, "e" * 32, 0, 1, 5, 8801,
                                    "1" * 16, echo="f" * 16))
    a.node.beacon._on_datagram(Datagram("192.168.1.77", stranger, False))
    assert a.node.beacon.stats.unsolicited_welcomes == before + 1
    assert a.node.beacon.peer("d" * 32) is None
    old = mb.encode(mb.Message("welcome", b.node_id, b.boot_id, 0, 1, 5, 8801, "2" * 16,
                               echo="0" * 16))
    a.node.beacon._on_datagram(Datagram(b.address, old, False))
    assert a.node.beacon.stats.unsolicited_welcomes == before + 2


# -- RPC authorisation, rate limits ---------------------------------------------------

def call(w, src, dst, kind, body):
    out = []
    src.node.rpc.call(dst.address, kind, body, lambda r, e: out.append((r, e)), 2)
    w.run(1)
    return out[0]


def test_rpc_flood_is_rate_limited_per_source_and_others_are_unaffected():
    w = settled(3, seed=4)
    a, b, c = w.running()
    refused = ok = 0
    for _ in range(int(mesh_rpc.RATE_CAPACITY) + 150):
        res = b.node.rpc._dispatch(a.address, b"ping\n{}")
        refused += res is None
        ok += res is not None
    assert refused >= 140 and ok >= 190 and b.node.rpc.rate_limited >= 140
    assert b.node.rpc._dispatch(c.address, b"ping\n{}") is not None
    w.run(3)
    assert b.node.rpc._dispatch(a.address, b"ping\n{}") is not None      # refills


def test_protected_calls_refuse_non_lan_and_blocked_sources_but_ping_stays_public():
    w = settled(2, seed=5)
    a, b = w.running()
    assert b.node.rpc._dispatch("8.8.8.8", b"sync\n{}") is None
    assert b.node.rpc._dispatch("8.8.8.8", b"ping\n{}") is not None
    assert b.node.rpc.denied == 1
    assert b.node.rpc._dispatch(a.address, b"sync\n{}") is not None


def test_strict_mode_requires_a_known_member_to_sync():
    w = ms.SimWorld(6, FullNode, strict=True)
    a = w.add("a")
    w.run(1)
    assert a.node.rpc._dispatch("192.168.1.200", b"sync\n{}") is None     # stranger
    b = w.add("b")
    w.run(5)
    assert a.node.rpc._dispatch(b.address, b"sync\n{}") is not None       # seen via presence
    assert w.converged()


# -- revocation -------------------------------------------------------------------------

def test_revoking_a_peer_removes_it_and_refuses_everything_from_it_until_unblocked():
    w = settled(4, seed=7)
    a, b = w.running()[0], w.running()[1]
    w.add_target(b, "from-b")
    w.run(2)
    assert "from-b" in a.node.target_ids()
    a.node.replicator.revoke(b.node_id)
    assert a.node.publisher.flush().node(b.node_id) is None
    assert "from-b" not in a.node.target_ids()
    assert any(isinstance(e, mem.NodeDown) and e.reason == "revoked"
               for e in a.node.membership_events)
    w.run(30)
    assert a.node.membership.member(b.node_id) is None             # beats ignored
    assert call(w, b, a, "push", {"records": [b.node.state.own.to_wire()]})[0] is None
    assert call(w, b, a, "sync", {"hash": "x", "digest": {}})[0] is None
    others = [h for h in w.running() if h not in (a, b)]
    assert all(h.node.membership.member(b.node_id) for h in others)
    a.node.membership.unblock(b.node_id)
    assert w.run_until(lambda: a.node.membership.member(b.node_id) is not None, 15.0) is not None
    assert w.run_until(lambda: "from-b" in a.node.target_ids(), 15.0) is not None


# -- flooding and soak ---------------------------------------------------------------------

def test_hostile_flood_for_a_simulated_minute_keeps_every_table_bounded_and_peers_intact():
    w = settled(4, seed=8)
    victim = w.running()[0]
    legit = {h.node_id for h in w.running()}
    for second in range(60):
        for i in range(120):
            n = second * 120 + i
            src = f"10.9.{n % 200}.{n % 250 + 1}"
            payload = mb.encode(mb.Message("heartbeat", f"{n + 9000:032x}", "1" * 32, 0, 1, 5,
                                           8801, "%016x" % n))
            victim.node.beacon._on_datagram(Datagram(src, payload, True))
            victim.node.rpc._dispatch(src, b"sync\n" + json.dumps(
                {"hash": "x", "digest": {}}).encode())
        w.run(1)
    beacon = victim.node.beacon
    assert len(beacon.peers()) <= mb.MAX_PEERS
    assert len(beacon._buckets) <= mb.MAX_BUCKETS
    assert len(victim.node.rpc._buckets) <= mesh_rpc.MAX_BUCKETS
    assert len(victim.node.membership.members()) <= mm.MAX_NODES
    assert legit <= {m.node_id for m in victim.node.membership.members()} | {victim.node_id}
    assert len(victim.node.state.records()) <= mm.MAX_NODES


# -- poisoned and malformed data ----------------------------------------------------------------

def test_poisoned_names_and_urls_are_rejected_not_displayed():
    w = settled(2, seed=9)
    a, b = w.running()
    good = b.node.state.own.to_wire()
    for field, value in (("name", "evil\x1b[31mname"), ("name", "<script>" * 20),
                         ("addresses", ["http://evil/"]), ("capabilities", ["javascript:x"])):
        bad = dict(good, rev=good["rev"] + 5, **{field: value})
        reply, _ = call(w, b, a, "push", {"records": [bad]})
        assert reply["accepted"] == 0, field
    assert a.node.state.get(b.node_id).rev == good["rev"]


hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as hst  # noqa: E402

JSON = hst.recursive(hst.none() | hst.booleans() | hst.integers() | hst.text(max_size=20),
                     lambda inner: hst.lists(inner, max_size=4)
                     | hst.dictionaries(hst.text(max_size=8), inner, max_size=5), max_leaves=20)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(hst.binary(max_size=600))
def test_rpc_dispatch_never_raises_on_arbitrary_bytes(blob):
    _ROUTER._dispatch("192.168.1.9", blob)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(JSON)
def test_sync_and_push_handlers_never_raise_or_corrupt_state(body):
    node = _ROUTER_NODE
    before = node.state.digest()
    if isinstance(body, dict):
        node.replicator._on_sync("192.168.1.9", body)
        node.replicator._on_push("192.168.1.9", body)
    assert node.state.digest().keys() >= before.keys() and node.state.own.rev == before[
        node.node_id][1]


@pytest.fixture(autouse=True, scope="module")
def _fuzz_targets():
    global _ROUTER, _ROUTER_NODE
    w = settled(2, seed=11)
    _ROUTER_NODE = w.running()[0].node
    _ROUTER = _ROUTER_NODE.rpc
    yield


_ROUTER = None
_ROUTER_NODE = None


# -- structure -------------------------------------------------------------------------------------

def test_mesh_modules_never_touch_playback_or_arbitrary_network_clients():
    forbidden = {"cast_session", "cast_control", "streamer", "dlna", "castctl", "server",
                 "urllib", "requests", "subprocess", "http", "ssl", "gi"}
    core = ("model", "ports", "beacon", "rpc", "membership", "state", "sync", "roles",
            "visibility", "cache", "clients", "policy")
    for name in core:                             # adapters (udp/http/transport/service) do I/O
        path = SRC / f"mesh_{name}.py"
        tree = ast.parse(path.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        assert not names & forbidden, (path.name, names & forbidden)


def test_authorisation_denials_are_counted_by_the_policy():
    from mesh_policy import MeshPolicy
    policy = MeshPolicy(strict=True, member_addresses=lambda: ["192.168.1.5"],
                        is_blocked=lambda a: a == "192.168.1.6")
    assert policy.allow("192.168.1.5", "sync") and policy.allow("192.168.1.5:9000", "push")
    assert not policy.allow("192.168.1.6", "sync") and not policy.allow("8.8.8.8", "sync")
    assert not policy.allow("192.168.1.7", "sync") and policy.denials == 3
    assert MeshPolicy().allow("192.168.1.7", "sync") and not MeshPolicy().allow("1.1.1.1", "x")
