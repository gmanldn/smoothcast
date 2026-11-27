import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_trust as nt

EP = "192.168.1.9:8765"


def paired(tmp_path=None, scopes=("media_read",)):
    t = nt.Trust("me", tmp_path)
    info = t.begin("peer", "Kitchen", EP)
    assert t.approve("peer", info["sas"], list(scopes)) == (True, "")
    return t


def test_sas_matches_on_both_sides_and_wrong_code_rejected():
    a, b = nt.Trust("A"), nt.Trust("B")
    assert a.begin("B", "b", EP)["sas"] == b.begin("A", "a", EP)["sas"]
    assert a.approve("B", "000000" if a.begin("B", "b", EP)["sas"] != "000000" else "111111", ["media_read"])[0] is False
    assert nt.Trust("me").begin("me", "x", EP) is None


def test_scopes_independent_and_nonce_single_use():
    t = paired(scopes=("media_read", "incoming_copy"))
    assert t.authorise("peer", "media_read", EP, "n1") == (True, "")
    assert not t.authorise("peer", "media_read", EP, "n1")[0]                 # replay
    assert not t.authorise("peer", "receiver_control", EP, "n2")[0]           # not granted
    t.set_scope("peer", "media_read", False)
    assert not t.authorise("peer", "media_read", EP, "n3")[0]
    assert t.authorise("peer", "incoming_copy", EP, "n4")[0]


def test_spoofed_endpoint_unknown_and_revoked_peers_denied():
    t = paired()
    assert "moved" in t.authorise("peer", "media_read", "10.0.0.66:8765", "n1")[1]
    assert not t.authorise("stranger", "media_read", EP, "n2")[0]
    assert t.revoke("peer") and not t.authorise("peer", "media_read", EP, "n3")[0]


def test_trust_survives_restart_but_pending_and_nonces_do_not(tmp_path):
    f = tmp_path / "trust.json"
    t = paired(f)
    t.authorise("peer", "media_read", EP, "n1"); t.begin("other", "x", EP)
    r = nt.Trust("me", f)
    assert "peer" in r.peers and r.authorise("peer", "media_read", EP, "n1")[0]
    assert not r.approve("other", "x", ["media_read"])[0]
    assert [p.name for p in f.parent.iterdir()] == ["trust.json"]
