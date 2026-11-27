import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import house_health as hh

HB = {"node": "Lounge PC", "version": "2.2.10", "platform": "linux", "uptime_s": 100, "sessions": 1, "roots": {"Movies": 500 * 10**9}, "encoders": ["nvenc", "cpu"]}


def test_validate_accepts_good_and_rejects_oversized_malformed_and_paths():
    ok, _ = hh.validate(HB); assert ok["encoders"] == ["cpu", "nvenc"] and ok["roots"] == {"Movies": 500 * 10**9}
    assert hh.validate(json.dumps(HB))[0] and hh.validate("x" * 3000) == (None, "too_large")
    assert hh.validate({**HB, "pad": "x" * 3000})[1] == "too_large"
    for bad, why in [({**HB, "roots": {"/home/sam/Movies": 1}}, "bad_root"), ({**HB, "roots": {"C:\\Users\\sam": 1}}, "bad_root"),
                     ({**HB, "node": "sam@laptop"}, "bad_node"), ({**HB, "node": "/home/sam"}, "bad_node"), ({**HB, "version": "v2"}, "bad_version"),
                     ({**HB, "platform": "amiga"}, "malformed"), ({**HB, "uptime_s": -1}, "malformed"), ({**HB, "sessions": True}, "malformed"),
                     ({**HB, "encoders": ["magic"]}, "malformed"), ({**HB, "roots": {"a": "big"}}, "bad_root"), ({"node": "x"}, "malformed"),
                     ([], "malformed"), ("{nope", "malformed"), (None, "malformed")]:
        assert hh.validate(bad) == (None, why), bad
    assert hh.validate({**HB, "roots": {f"r{i}": 1 for i in range(17)}})[0] is None


def test_no_path_or_username_in_clean_heartbeat():
    clean = hh.validate(HB)[0]; blob = json.dumps(clean)
    assert "/" not in blob and "\\" not in blob and "@" not in blob


def rows(*nodes, now=100.0, receivers=()):
    b = hh.Board()
    for hb, t in nodes:
        assert b.heartbeat(hb, t)[0]
    for r in receivers:
        b.set_receiver(*r)
    return b, {r["node"]: r for r in b.rows(now)}


def test_rules_table_disk_version_offline():
    G = 10**9
    cases = [(100 * G, 99.0, "green", []), (4 * G, 99.0, "amber", ["Disk nearly full on N"]), (G // 2, 99.0, "red", ["Disk full on N"]),
             (100 * G, 10.0, "red", ["hasn't been seen"]), (5 * G, 99.0, "green", []), (G, 99.0, "amber", ["nearly full"])]
    for free, seen, want, texts in cases:
        _, r = rows(({**HB, "node": "N", "roots": {"Movies": free}}, seen), ({**HB, "node": "New"}, 99.0))
        assert r["N"]["status"] == want, (free, seen)
        assert all(any(t in x for x in r["N"]["reasons"]) for t in texts), (free, seen, r["N"]["reasons"])
    _, r = rows(({**HB, "node": "Old", "version": "2.2.9"}, 99.0), ({**HB, "node": "New"}, 99.0))
    assert r["Old"]["status"] == "amber" and r["Old"]["reasons"] == ["Update available"] and r["New"]["status"] == "green"
    _, r = rows(({**HB, "node": "N", "roots": {"A": 4 * 10**9, "B": 10**8}}, 99.0)); assert r["N"]["status"] == "red" and len(r["N"]["reasons"]) == 2


def test_offline_boundary_receive_time_and_sorting():
    b, r = rows((HB, 40.0), now=100.0); assert r["Lounge PC"]["online"] and r["Lounge PC"]["last_seen_s"] == 60
    assert b.rows(100.1)[0]["status"] == "red" and not b.rows(100.1)[0]["online"]
    b.set_receiver("TV", False, 100); b.heartbeat({**HB, "node": "A"}, 100)
    order = [x["node"] for x in b.rows(100)]; assert order[0] == "TV" and "isn't answering" in b.rows(100)[0]["reasons"][0]
    assert b.summary(100) == "1 of 3 need attention." and hh.Board().summary(0) == "Everything looks good."


def test_bounded_memory_under_hundreds_of_heartbeats_and_rejects_dont_store():
    b = hh.Board()
    for i in range(500):
        b.heartbeat({**HB, "node": f"n{i}"}, float(i))
    assert len(b.nodes) == hh.MAX_NODES and "n0" not in b.nodes and "n499" in b.nodes
    assert b.heartbeat({"junk": 1}, 1) == (False, "malformed") and len(b.nodes) == hh.MAX_NODES
    for i in range(800):
        b.set_receiver(f"r{i}", True, 1.0)
    assert len(b.receivers) <= 500


def test_multi_node_simulated_house_converges():
    b = hh.Board()
    for i, (v, free) in enumerate([("2.2.10", 900 * 10**9), ("2.2.9", 900 * 10**9), ("2.2.10", 2 * 10**9)]):
        b.heartbeat({**HB, "node": f"n{i}", "version": v, "roots": {"Lib": free}}, 90.0)
    st = {r["node"]: r["status"] for r in b.rows(100)}; assert st == {"n2": "amber", "n1": "amber", "n0": "green"}
