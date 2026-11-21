"""Local reliability metrics have explicit timing and privacy bounds."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import reliability_metrics as metrics

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reliability_benchmark


def test_session_sli_events_use_monotonic_intervals_and_confirmed_playing():
    session = metrics.SessionMetrics("cast", started=10.0, wall_time=1_700_000_000)
    session.mode = "transcode"
    session.encoder = "software"
    session.observe_state("BUFFERING", now=11.0)
    session.observe_state("PLAYING", now=12.0)
    session.begin_seek(now=13.0)
    session.confirm_seek(now=13.25)
    session.observe_state("BUFFERING", now=17.0)
    session.observe_state("PLAYING", now=20.0)
    summary = session.finish("completed", now=25.0)

    assert summary["first_playing_ms"] == 2000
    assert summary["playing_ms"] == 10_000
    assert summary["buffering_ms"] == 4_000
    assert summary["stall_ratio"] == 0.2857
    assert summary["rebuffer_count"] == 1
    assert summary["seek_latency_ms"] == [250.0]
    assert summary["outcome"] == "completed"


def test_unknown_or_unconfirmed_measurements_remain_unknown():
    session = metrics.SessionMetrics("other", started=1.0, wall_time=1_700_000_000)
    session.observe_state("GARBAGE", now=4.0)
    summary = session.finish("failed", now=5.0)
    assert summary["protocol"] == "cast"
    assert summary["first_playing_ms"] is None
    assert summary["stall_ratio"] is None
    assert summary["recovery_ms"] is None
    assert summary["cpu_peak_percent"] is None


def test_store_is_allowlisted_bounded_by_age_and_redacts_private_fields(tmp_path):
    path = tmp_path / "reliability.json"
    wall = datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp()
    for i in range(metrics.MAX_SUMMARIES + 5):
        session = metrics.SessionMetrics("dlna", started=10.0, wall_time=wall + i)
        summary = session.finish("completed", now=11.0)
        summary["path"] = "/home/alice/Movies/private-film.mkv"
        summary["receiver_ip"] = "192.168.1.77"
        metrics.append(summary, path, now=wall + i)
    rows = metrics.recent(path, now=wall + metrics.MAX_SUMMARIES + 5)
    assert len(rows) == metrics.MAX_SUMMARIES
    blob = json.dumps(rows)
    assert "/home/alice" not in blob
    assert "192.168.1.77" not in blob
    assert all("path" not in row and "receiver_ip" not in row for row in rows)
    assert path.stat().st_mode & 0o777 == 0o600
    dashboard = metrics.dashboard_summary(
        path, now=wall + metrics.MAX_SUMMARIES + 5,
    )
    assert dashboard["sample_count"] == metrics.MAX_SUMMARIES
    assert dashboard["protocols"]["dlna"] == metrics.MAX_SUMMARIES
    assert "private-film" not in json.dumps(dashboard)


def test_store_prunes_expired_summaries_and_rejects_invalid_values(tmp_path):
    path = tmp_path / "reliability.json"
    old_wall = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    old = metrics.SessionMetrics("cast", started=1, wall_time=old_wall).finish(
        "completed", now=2,
    )
    metrics.append(old, path, now=old_wall)
    assert metrics.recent(path, now=old_wall + (metrics.MAX_AGE_DAYS + 1) * 86400) == []

    invalid = dict(old, protocol="cast", stall_ratio=4.2)
    try:
        metrics.append(invalid, path)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid SLI sample was stored")


def test_fakecast_benchmark_uses_a_profile_matched_wide_tolerance():
    result = reliability_benchmark.measure(
        3, runner=iter((20, 30, 40)).__next__,
        runner_profile={"runner": "ci", "machine": "x86_64", "python": "3.13"},
    )
    assert result["median_playing_ms"] == 30
    profile = result["profile"]
    assert reliability_benchmark.compare(result, None)["status"] == "baseline-pending"
    baseline = {"profile": profile, "median_playing_ms": 30}
    assert reliability_benchmark.compare(result, baseline)["status"] == "pass"
    slower = dict(result, median_playing_ms=61)
    assert reliability_benchmark.compare(slower, baseline)["status"] == "regression"
    mismatch = dict(baseline, profile={"runner": "other"})
    assert reliability_benchmark.compare(result, mismatch)["status"] == "profile-mismatch"


def test_session_helpers_keep_ui_state_in_memory_and_submit_storage_to_worker(monkeypatch):
    owner = SimpleNamespace()
    stored = []
    jobs = []
    monkeypatch.setattr(metrics, "append", lambda summary: stored.append(summary))

    def run(work, *, done=None, failed=None, domain=None):
        jobs.append(domain)
        try:
            result = work()
        except Exception as exc:
            if failed:
                failed(str(exc))
        else:
            if done:
                done(result)

    metrics.start_attempt(owner, "cast")
    session = SimpleNamespace(mode="transcode", used_software_fallback=True)
    metrics.accept_attempt(owner, session, run)
    metrics.observe(owner, "PLAYING")
    metrics.finish_active(owner, "completed", run)

    assert jobs == ["media"]
    assert len(stored) == 1
    assert stored[0]["mode"] == "transcode"
    assert stored[0]["encoder"] == "software"
    assert stored[0]["first_playing_ms"] is not None

