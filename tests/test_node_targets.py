import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_targets as nt

PEERS = [{"id": "b", "name": "Bedroom", "accepts_playback": True, "last_seen": 100},
         {"id": "c", "name": "Cellar", "accepts_playback": False, "last_seen": 100},
         {"id": "d", "name": "Den", "accepts_playback": True, "last_seen": 10},
         {"id": "e", "name": "Eve", "accepts_playback": True, "last_seen": 100}]


def test_readiness_states_and_ordering():
    rows = nt.targets(PEERS, {"b", "c", "d"}, {}, 105)
    st = {r["id"]: r["status"] for r in rows}
    assert st == {"b": nt.READY, "c": nt.NOT_ENABLED, "d": nt.OFFLINE, "e": nt.NOT_TRUSTED}
    assert rows[0]["id"] == "b" and rows[0]["selectable"] and not rows[-1]["selectable"]
    assert nt.targets(PEERS, {"b"}, {"b": "roomA"}, 105)[0]["status"] == nt.BUSY


def test_fence_one_owner_and_stale_commands_rejected():
    f = nt.Fence()
    e, _ = f.claim("b", "roomA")
    assert f.claim("b", "roomB")[0] is None and f.claim("b", "roomA")[0] == e
    assert f.accept("b", "roomA", e, "pause")[0]
    assert not f.accept("b", "roomB", e, "pause")[0] and not f.accept("b", "roomA", e + 1, "pause")[0]


def test_release_then_new_owner_gets_new_epoch_and_old_epoch_dies():
    f = nt.Fence(); e1, _ = f.claim("b", "A")
    f.release("b", "other"); assert f.owners() == {"b": "A"}
    f.release("b", "A"); e2, _ = f.claim("b", "B")
    assert e2 != e1 and not f.accept("b", "A", e1, "seek")[0] and f.accept("b", "B", e2, "seek")[0]
