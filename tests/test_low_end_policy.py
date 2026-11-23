"""Low-end adaptation: pure decision, durable identity cache, worker isolation (#515)."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import low_end_policy as low  # noqa: E402


def source(fps=30.0, *, audio_only=False):
    return SimpleNamespace(fps=fps, is_audio_only=audio_only)


@pytest.mark.parametrize(("speed", "fps", "expected"), [
    (None, 30.0, "saver"), (0.0, 30.0, "saver"),
    (38.9, 30.0, "saver"), (39.0, 30.0, "balanced"),
    (90.0, 30.0, "balanced"), (20.0, 15.0, "balanced"),
    (19.4, 15.0, "saver"), (38.9, 60.0, "saver"),
    (39.0, 60.0, "balanced"), (math.nan, 30.0, "saver"),
    (math.inf, 30.0, "saver"), (-1, 30.0, "saver"),
])
def test_choose_tier_measured_headroom(speed, fps, expected):
    assert low.choose_tier(speed, source(fps)) == expected


def test_invalid_source_rate_is_conservative():
    assert low.choose_tier(38.0, source(math.nan)) == "saver"
    assert low.choose_tier(39.0, source(None)) == "balanced"


def test_manual_override_wins_even_if_benchmark_disagrees(tmp_path):
    cache = tmp_path / "perf.json"
    assert low.persist(5, path=cache, identity="cpu", now=100)
    for quality in ("high", "balanced", "saver"):
        settings = {"quality_auto": False, "quality": quality}
        assert low.effective_quality(settings, source(), path=cache, identity="cpu") == quality
    assert low.effective_quality(
        {"quality_auto": True, "quality": "high"},
        source(), path=cache, identity="cpu",
    ) == "saver"  # stale measurement is never optimistically high


def test_cache_round_trip_expiry_corruption_and_identity(tmp_path):
    cache = tmp_path / "state.json"
    assert low.persist(41.0, path=cache, identity="machine-A", now=5000)
    assert low.cached_speed(cache, identity="machine-A", now=5100) == 41.0
    assert low.cached_speed(cache, identity="machine-B", now=5100) is None
    assert low.cached_speed(cache, identity="machine-A", now=5000 + low.GOOD_TTL + 1) is None
    cache.write_text("{not JSON", encoding="utf-8")
    assert low.cached_speed(cache, identity="machine-A", now=5100) is None
    assert low.persist(math.nan, path=cache, identity="machine-A", now=5000) is False
    assert cache.read_text(encoding="utf-8") == "{not JSON"


def test_failed_probe_cached_briefly_not_forever(tmp_path):
    cache = tmp_path / "state.json"
    assert low.persist(None, path=cache, identity="machine-A", now=5000)
    assert low._record(cache, "machine-A", now=5001) is not None
    assert low._record(cache, "machine-A", now=5000 + low.FAILED_TTL + 1) is None
    assert low.cached_speed(cache, identity="machine-A", now=5001) is None


def test_background_probe_does_not_block_ui_and_is_singleflight(tmp_path):
    cache = tmp_path / "state.json"
    began = threading.Event()
    proceed = threading.Event()
    workers = []
    main_id = threading.get_ident()

    def runner(args, **_kwargs):
        workers.append(threading.get_ident())
        began.set()
        assert proceed.wait(3)
        return SimpleNamespace(returncode=0, stderr="frame=90 fps= 45.0")

    try:
        assert low.schedule_probe(enabled=True, path=cache, identity="M", runner=runner)
        assert began.wait(3)
        assert low.schedule_probe(enabled=True, path=cache, identity="M", runner=runner) is False
        assert len(workers) == 1 and workers[0] != main_id
    finally:
        proceed.set()
    deadline = time.monotonic() + 3.0
    while low._running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not low._running
    assert low.cached_speed(cache, identity="M") == 45.0
    assert low.schedule_probe(enabled=True, path=cache, identity="M", runner=runner) is False
    assert low.schedule_probe(enabled=False, path=tmp_path / "other.json",
                              identity="M", runner=runner) is False


def test_worker_failure_records_conservative_retry_without_crashing(tmp_path):
    cache = tmp_path / "state.json"
    with mock.patch.object(low.benchmark, "run_probe", return_value=None):
        assert low.schedule_probe(enabled=True, path=cache, identity="M")
        deadline = time.monotonic() + 3
        while low._running and time.monotonic() < deadline:
            time.sleep(0.01)
    assert low._record(cache, "M") is not None
    assert low.cached_speed(cache, identity="M") is None


def test_machine_identity_is_hashed_and_state_has_no_host_or_path(tmp_path):
    cache = tmp_path / "state.json"
    with mock.patch.object(low.platform, "processor", return_value="Private CPU model"), \
            mock.patch.object(low.platform, "machine", return_value="x86_64"), \
            mock.patch.object(low.shutil, "which", return_value=None):
        identity = low.machine_key()
    assert len(identity) == 64
    assert "Private" not in identity
    assert low.persist(39.0, path=cache, identity=identity)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert set(data) == {"schema", "machine", "fps", "at"}
    assert data["machine"] == identity
    if sys.platform != "win32":
        assert cache.stat().st_mode & 0o077 == 0


def test_budget_is_informational_not_a_performance_claim():
    scenario = low.budget()
    assert scenario["minimum_software_encode_x"] == 1.3
    assert scenario["first_frame_p95_ms"] == 4000
    assert "informational" in scenario["measurement"]
