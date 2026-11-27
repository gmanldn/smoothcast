import stream_health
import stream_health_view as v


def test_no_snapshot_is_not_measured():
    assert v.rows(None) == [("Stream health", "not measured")]


def test_unmeasured_series_say_so_and_never_invent_numbers():
    rows = dict(v.rows(stream_health.StreamHealth().snapshot()))
    assert rows["Throughput"] == "not measured" and rows["HLS latency"] == "not measured"


def test_measured_values_render_with_units_and_failure_rate():
    h = stream_health.StreamHealth()
    for k in (4000, 6000):
        h.throughput(k)
    h.latency(850)
    h.segment(True)
    h.segment(False, "seg7")
    h.recovered("encoder restart")
    rows = dict(v.rows(h.snapshot()))
    assert rows["Throughput"].startswith("6.0 Mbit/s")
    assert "850 ms" in rows["HLS latency"]
    assert "1 ok, 1 failed (50.0% failing)" == rows["Segments"]
    assert rows["Recoveries"] == "1"
    assert any("encoder restart" in e for e in v.recent_events(h.snapshot()))
