import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import energy_aware as e


def test_scoring_table():
    rows = [({}, 0), ({"awake": True}, 0), ({"on_battery": True}, 50), ({"user_active": True}, 20), ({"cpu_load_1m": 0.5}, 5),
            ({"cpu_load_1m": 2.0}, 20), ({"cpu_load_1m": 99}, 40), ({"awake": False}, 100), ({"on_battery": True, "user_active": True, "cpu_load_1m": 1}, 80),
            ({"on_battery": False, "user_active": False, "cpu_load_1m": 0}, 0), ({"cpu_load_1m": "x"}, 0), ({"cpu_load_1m": True}, 0), ({"cpu_load_1m": -3}, 0)]
    for node, want in rows:
        assert e.score(node) == want, node


def test_three_node_scenario_prefers_awake_idle_node():
    nodes = [{"id": "laptop", "on_battery": True, "cpu_load_1m": 0.2, "latency_ms": 1},
             {"id": "desk", "user_active": True, "cpu_load_1m": 1.5, "latency_ms": 1},
             {"id": "nas", "cpu_load_1m": 0.1, "latency_ms": 5}]
    assert e.choose(nodes)["id"] == "nas"
    assert e.choose(nodes, lambda o: o["id"] != "nas")["id"] == "desk"        # 35 beats battery's 52
    assert e.choose([{"id": "z", "awake": False}, {"id": "y"}])["id"] == "y" and e.choose(nodes, lambda o: False) is None and e.choose([]) is None


def test_ties_break_on_latency_then_node_id_and_missing_metrics_are_idle():
    assert e.choose([{"id": "b", "latency_ms": 9}, {"id": "a", "latency_ms": 2}, {"id": "c", "latency_ms": 2}])["id"] == "a"
    assert e.choose([{"id": "b"}, {"id": "a"}])["id"] == "a" and e.score({}) == 0


def test_active_stream_never_moved_just_to_save_energy():
    cur, best = {"id": "laptop", "on_battery": True}, {"id": "nas"}
    assert e.keep_stream(cur, best, active=True) is cur and e.keep_stream(cur, best, active=False) is best
    assert e.keep_stream(None, best, active=True) is best and e.keep_stream(cur, None, active=False) is None


def test_published_fields_are_sanitised():
    assert e.fields(True, 0.456, False) == {"on_battery": True, "cpu_load_1m": 0.5, "user_active": False}
    assert e.fields() == {} and e.fields("yes", "x", 1) == {} and e.fields(cpu_load_1m=True) == {} and e.fields(cpu_load_1m=-1) == {}
