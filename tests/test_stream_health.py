import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stream_health import StreamHealth


def test_nothing_measured_reports_unknown_not_ok():
    s = StreamHealth().snapshot()
    assert s["throughput_kbps"] is None and s["latency_ms"] is None
    assert s["decoder"] == "unknown" and s["failure_rate"] is None


def test_series_events_and_counts():
    h = StreamHealth(clock=lambda: 7.0)
    for v in (100, 200, 300, float("nan"), True, -1, "x"):
        h.throughput(v)
    h.latency(40)
    h.segment(True); h.segment(False, "seg7.ts"); h.recovered("retry")
    h.decoder_state("playing")
    s = h.snapshot()
    assert s["throughput_kbps"]["samples"] == 3 and s["throughput_kbps"]["median"] == 200
    assert s["latency_ms"]["last"] == 40 and s["failure_rate"] == 0.5 and s["recoveries"] == 1
    assert [e["kind"] for e in s["recent_events"]] == ["segment_failed", "recovered"]
    assert s["decoder"] == "playing"


def test_unknown_decoder_state_is_not_trusted_and_series_are_bounded():
    h = StreamHealth()
    h.decoder_state("great")
    assert h.decoder == "unknown"
    for i in range(500):
        h.throughput(i); h.segment(False)
    assert h.snapshot()["throughput_kbps"]["samples"] == 60 and len(h.snapshot()["recent_events"]) == 10
