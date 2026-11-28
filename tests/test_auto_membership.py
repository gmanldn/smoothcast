import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import known_nodes as kn

FP1, FP2 = "ab" * 16, "cd" * 16


def test_compatible_peer_auto_joins_when_on_and_waits_when_off():
    k = kn.Known()
    assert k.observe("node-dad-1", FP1, "Dad's laptop")["action"] == "join" and "node-dad-1" in k.nodes
    off = kn.Known()
    assert off.observe("node-dad-1", FP1, "Dad's laptop", auto_join=False)["action"] == "pending" and off.nodes == {}
    assert kn.Known().observe("node-old-1", FP1, compatible=False)["action"] == "reject"
    assert kn.SETTING == "Join other SmoothCast computers automatically"


def test_fingerprint_change_detected_not_merged_and_surfaced_in_health():
    k = kn.Known()
    k.observe("node-dad-1", FP1, "Dad's laptop")
    r = k.observe("node-dad-1", FP2, "Dad's laptop")
    assert r["action"] == "identity_changed" and r["node_id"] != "node-dad-1" and r["node_id"].startswith("node-dad-1~")
    assert r["message"] == "Dad's laptop was reinstalled or replaced. Accept the new identity?" and k.nodes["node-dad-1"]["fp"] == FP1
    assert k.observe("node-dad-1", FP2, "x")["node_id"] == r["node_id"]               # stable quarantine id
    assert k.observe("node-dad-1", FP1)["action"] == "join"                           # the original still joins as itself
    h = k.health_rows()
    assert h[0]["status"] == "amber" and h[0]["node"] == "node-dad-1" and "Accept the new identity?" in h[0]["reasons"][0]


def test_cloned_disk_image_both_shown_until_one_accepted():
    k = kn.Known()
    k.observe("node-clone", FP1, "PC")
    a, b = k.observe("node-clone", FP2, "PC"), k.observe("node-clone", "ef" * 16, "PC")
    assert a["node_id"] != b["node_id"] and k.health_rows()[0]["identities"] == 3
    assert not k.accept("node-clone", "00" * 16) and k.accept("node-clone", FP2) and k.nodes["node-clone"]["fp"] == FP2 and k.health_rows() == []
    assert k.observe("node-clone", FP2)["action"] == "join"


def test_persistence_atomic_file_shape_and_corruption(tmp_path):
    p = tmp_path / "known_nodes.json"
    t = [100.0]
    k = kn.Known(p, clock=lambda: t[0])
    k.observe("node-dad-1", FP1, "Dad's laptop")
    d = json.loads(p.read_text())
    assert d == {"_schema": 1, "version": 1, "nodes": {"node-dad-1": {"fp": FP1, "first_seen": 100.0, "name": "Dad's laptop"}}}
    assert kn.Known(p).observe("node-dad-1", FP2)["action"] == "identity_changed"      # pin survives restart
    p.write_text("{garbage")
    assert kn.Known(p).nodes == {}
    p.write_text(json.dumps({"version": 9, "nodes": {"a": {"fp": "x"}}}))
    assert kn.Known(p).nodes == {}


def test_invalid_ids_fingerprints_and_cap_rejected():
    k = kn.Known()
    for nid, fp in [("../x", FP1), ("node-1", "zz"), ("n", FP1), (None, FP1), ("node-1", None), ("node-1", "ab")]:
        assert k.observe(nid, fp)["action"] == "reject"
    for i in range(kn.MAX_NODES):
        k.nodes[f"node-{i:04d}"] = {"fp": FP1}
    assert k.observe("node-new-1", FP1)["action"] == "reject"


def test_design_doc_describes_mesh_member_tier_and_new_principle():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "MESH_DESIGN.md").read_text()
    assert "Mesh member" in doc and "Public (beacon)" in doc and "Web client" in doc
    assert "Discovery is a hint, pairing is trust" not in doc and "Join other SmoothCast computers automatically" in doc
