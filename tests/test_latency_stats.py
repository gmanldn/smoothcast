import json

from src import latency_stats as L


def test_buckets_and_percentiles_never_underreport():
    s = L.Stats()
    for ms in [0.5, 3, 3, 40, 40, 40, 40, 900, 900, 20000]:
        assert s.record("portal.request", ms)
    assert s.percentile("portal.request", 50) == 50.0
    assert s.percentile("portal.request", 95) == 30000.0
    assert s.percentile("missing", 50) is None
    assert s.summary()["portal.request"] == {"count": 10, "p50": 50.0, "p95": 30000.0, "p99": 30000.0}


def test_over_range_sample_is_infinite_not_dropped():
    s = L.Stats()
    s.record("startup", 99999)
    assert s.percentile("startup", 99) == float("inf")


def test_bad_names_and_values_are_refused_and_metrics_bounded():
    s = L.Stats()
    for bad in [("", 1), ("Bad Name", 1), ("a" * 60, 1), ("ok", -1), ("ok", float("nan")), ("ok", True), ("ok", "5"), (None, 1)]:
        assert not s.record(*bad)
    for i in range(L.MAX_METRICS):
        assert s.record(f"m{i}", 1)
    assert not s.record("one_too_many", 1) and len(s.snapshot()["metrics"]) == L.MAX_METRICS


def test_timer_uses_injected_clock():
    t = iter([10.0, 10.25])
    s = L.Stats(clock=lambda: next(t))
    with s.timer("shutdown"):
        pass
    assert s.percentile("shutdown", 50) == 250.0


def test_snapshot_round_trips_through_json_and_merges():
    a = L.Stats()
    a.record("startup", 100)
    b = L.Stats()
    b.record("startup", 100)
    b.restore(json.loads(json.dumps(a.snapshot())))
    assert b.summary()["startup"]["count"] == 2


def test_restore_ignores_foreign_or_corrupt_data():
    s = L.Stats()
    s.restore({"bounds_ms": [1], "metrics": {"x": [1, 2]}})
    s.restore({"bounds_ms": list(L.BOUNDS_MS), "metrics": {"x": [1, 2], "y": ["a"] * 15, "Bad": [0] * 15}})
    s.restore("junk")
    assert s.snapshot()["metrics"] == {}


def test_correlation_ids():
    cid = L.new_correlation_id()
    assert L.valid_correlation_id(cid) and len(cid) == 12
    assert L.new_correlation_id(lambda: "abcdef012345") == "abcdef012345"
    assert not any(L.valid_correlation_id(x) for x in ("", "ABCDEF012345", "short", None, "abcdef01234g"))


def test_save_then_load_round_trips_and_bad_files_give_empty(tmp_path):
    s = L.Stats()
    s.record("portal.request", 12)
    assert L.save(s, tmp_path) is True
    assert L.load(tmp_path).summary()["portal.request"]["count"] == 1
    (tmp_path / L.FILE_NAME).write_text("{not json")
    assert L.load(tmp_path).summary() == {}
    assert L.load(tmp_path / "missing").summary() == {}
    assert L.save(s, tmp_path / "missing") is False


def test_shared_is_one_instance():
    assert L.shared() is L.shared()
