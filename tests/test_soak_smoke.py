"""#464: the soak harness - verdict logic, a real smoke run, and injected leaks it must catch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import soak


def make(threads=2, fds=10, rss=40_000, maps=None, n=12):
    base = {"sessions": 31, "participants": 31, "dormant": 0, "votes": 4, "events": 200,
            "command_cache": 2, "attempts": 1, "lockouts": 0, "limiter": 100, "screens": 0,
            "uploads": 5}
    return [{"cycle": i * 10, "threads": threads, "fds": fds, "rss_kb": rss, "files": 5,
             "maps": {**base, **(maps or {})}} for i in range(1, n + 1)]


def series(**changes):
    """Samples where each named metric follows ``f(i)``; maps via ``maps=...``."""
    samples = make()
    for i, sample in enumerate(samples):
        for key, fn in changes.items():
            if key == "maps":
                sample["maps"].update({m: f(i) for m, f in fn.items()})
            else:
                sample[key] = fn(i)
    return samples


# --- verdict logic (pure) -------------------------------------------------
def test_flat_series_passes():
    result = soak.verdict(make())
    assert result["verdict"] == "pass" and result["failures"] == [] and result["warnings"] == []


def test_thread_or_fd_growth_after_warmup_fails_but_warmup_growth_is_ignored():
    assert soak.verdict(series(threads=lambda i: 2 + i))["verdict"] == "fail"
    assert "fds grew" in soak.verdict(series(fds=lambda i: 10 + i))["failures"][0]
    warm = series(threads=lambda i: 2 if i >= 3 else 1 + i)            # settles in the first 20-25%
    assert soak.verdict(warm)["verdict"] == "pass"


def test_bounded_maps_may_fill_up_to_their_cap_but_never_beyond_it():
    filling = series(maps={"limiter": lambda i: 40 * (i + 1)})          # 40 -> 480, cap 512
    assert soak.verdict(filling)["verdict"] == "pass"
    over = series(maps={"limiter": lambda i: 100 + 60 * i})             # reaches 760
    result = soak.verdict(over)
    assert result["verdict"] == "fail" and "map limiter reached" in result["failures"][0]
    assert soak.verdict(series(maps={"limiter": lambda i: 100 + 60 * i}), caps={"limiter": 10_000})["verdict"] == "pass"


def test_unknown_uncapped_maps_must_not_grow_but_upload_retention_only_warns():
    result = soak.verdict(series(maps={"mystery": lambda i: i}))
    assert result["verdict"] == "fail" and "uncapped map mystery" in result["failures"][0]
    ok = soak.verdict(series(maps={"uploads": lambda i: i * 3}))
    assert ok["verdict"] == "pass" and any("uploads grew" in w for w in ok["warnings"])


def test_rss_growth_is_a_warning_never_a_failure():
    result = soak.verdict(series(rss_kb=lambda i: 40_000 + i * 2_000))
    assert result["verdict"] == "pass" and any("RSS" in w for w in result["warnings"])
    assert soak.verdict(series(rss_kb=lambda i: 40_000 + (i % 2) * 300))["warnings"] == []


def test_too_few_samples_is_a_failure_not_a_silent_pass():
    assert soak.verdict(make(n=2))["verdict"] == "fail"


# --- the real thing -----------------------------------------------------------
def test_a_150_cycle_soak_passes_quickly_and_writes_a_report(tmp_path):
    started = time.monotonic()
    threads_before = threading.active_count()
    report_path = tmp_path / "soak-report.json"
    result = soak.run(150, report_path=report_path, quiet=True)
    assert time.monotonic() - started < 40, "smoke budget is ~20 s on a normal machine"
    assert result["verdict"] == "pass", result["failures"]
    counts = result["counts"]
    assert counts["seeks"] == 600 and counts["joins"] == 150 and counts["uploads"] >= 30
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["verdict"] == "pass" and saved["series"] and saved["simulated_hours"] > 1
    assert {"threads", "fds", "rss_kb", "files", "maps"} <= set(saved["series"][0])
    assert threading.active_count() <= threads_before, "the soak left threads running"


def test_cli_returns_nonzero_on_a_failed_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(soak, "run", lambda cycles, report_path=None, **k: {
        "verdict": "fail", "failures": ["x"], "warnings": [], "series": [], "counts": {}, "cycles": cycles})
    assert soak.main(["--cycles", "5", "--report", str(tmp_path / "r.json")]) == 1
    monkeypatch.setattr(soak, "run", lambda cycles, report_path=None, **k: {"verdict": "pass"})
    assert soak.main(["--cycles", "5", "--report", str(tmp_path / "r.json")]) == 0


# --- deliberate leaks must be caught ---------------------------------------------
def test_a_thread_leak_is_detected():
    def leak(cycle, _ctx):
        event = threading.Event()
        thread = threading.Thread(target=event.wait, name="soak-leak", daemon=True)
        thread.release = event.set                                     # type: ignore[attr-defined]
        thread.start()
    result = soak.run(40, hooks=[leak], quiet=True)
    assert result["verdict"] == "fail" and any("threads grew" in f for f in result["failures"])


def test_a_file_descriptor_leak_is_detected():
    if soak._fds() is None:
        pytest.skip("no /proc/self/fd on this platform")
    held = []
    try:
        result = soak.run(40, hooks=[lambda cycle, _ctx: held.append(open(os.devnull))], quiet=True)
    finally:
        for handle in held:
            handle.close()
    assert result["verdict"] == "fail" and any("fds grew" in f for f in result["failures"])


def test_an_unbounded_map_is_detected():
    def leak(cycle, ctx):
        for i in range(40):                                            # never-expiring lockouts
            ctx.server._lockouts[f"leak-{cycle}-{i}"] = 1e12
    result = soak.run(40, hooks=[leak], quiet=True)
    assert result["verdict"] == "fail" and any("map lockouts reached" in f for f in result["failures"])
