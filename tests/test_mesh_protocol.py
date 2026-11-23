"""#387: negotiate before state exchange on the real simulated mesh stack."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_sim as ms
from mesh_full_node import FullNode

INCOMPATIBLE = {
    "proto": 2, "min_proto": 2, "app_version": "2.0.0",
    "caps": ["mesh.records.v1"],
}


def two_nodes():
    world = ms.SimWorld(131, FullNode)
    world.join(2)
    world.assert_converged(5000)
    world.run(3)
    return world, *world.running()


def test_normal_v1_mesh_peers_negotiate_without_losing_convergence():
    world, a, b = two_nodes()
    negotiated = a.node.replicator.agreements[b.node_id]
    assert negotiated.proto == 1
    assert negotiated.supports("mesh.records.v1")
    world.add_target(b, "next-tv")
    world.run(2)
    assert "next-tv" in a.node.target_ids()


def test_legacy_sync_message_works_but_has_no_opt_in_capabilities():
    _world, a, b = two_nodes()
    agreement = b.node.replicator._agree({})
    assert agreement.proto == 1 and agreement.legacy and not agreement.caps
    response = b.node.replicator._on_sync(a.address, {"hash": "unknown", "digest": {}})
    assert response["hello"]["proto"] == 1
    assert "records" in response and "error" not in response


def test_incompatible_push_and_sync_are_refused_before_any_state_exchange():
    _world, a, b = two_nodes()
    before = b.node.publisher.view.fingerprint()
    wire = a.node.state.own.to_wire()
    reply = b.node.replicator._on_push(
        a.address, {"hello": INCOMPATIBLE, "records": [dict(wire, rev=999999)]},
    )
    assert reply["error"] == "incompatible_protocol"
    assert "accepted" not in reply
    reply = b.node.replicator._on_sync(
        a.address, {"hello": INCOMPATIBLE, "hash": "bad", "digest": {}},
    )
    assert reply["error"] == "incompatible_protocol"
    assert "digest" not in reply and "records" not in reply
    assert b.node.publisher.view.fingerprint() == before
    assert b.node.replicator.stats.compatibility_refusals >= 2


def test_bad_peer_response_cannot_import_foreign_records():
    _world, a, b = two_nodes()
    before = a.node.publisher.view.fingerprint()
    link = a.node.replicator._link(b.node_id)
    a.node.replicator._apply_sync_reply(
        link, b.address, {
            "hello": INCOMPATIBLE,
            "records": [dict(b.node.state.own.to_wire(), rev=999999)],
            "digest": {},
        },
    )
    assert a.node.publisher.view.fingerprint() == before
    assert a.node.replicator.stats.compatibility_refusals >= 1


def test_kill_switch_disables_capability_for_only_selected_peer():
    _world, a, b = two_nodes()
    hello = {"hello": b.node.replicator.hello.wire()}
    assert a.node.replicator._agree(hello, node_id=b.node_id).supports("mesh.records.v1")
    a.node.replicator.config.disabled_caps_by_peer[b.node_id] = frozenset(
        {"mesh.records.v1"},
    )
    assert not a.node.replicator._agree(hello, node_id=b.node_id).caps
    assert a.node.replicator._agree(hello, node_id="other").supports("mesh.records.v1")
