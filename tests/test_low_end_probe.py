"""The optional two-core Linux probe is offline, bounded and reproducible (#515)."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import low_end_probe  # noqa: E402


def test_affinity_nice_and_synthetic_source_are_applied_to_child_only():
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="frame= 120 fps= 45.0")

    result = low_end_probe.measure(
        "3,5", runner=run, which=lambda name: "/usr/bin/" + name)
    assert result["affinity"] == "3,5"
    assert result["measured_fps"] == 45.0
    assert result["recommended_tier"] == "balanced"
    argv, kwargs = calls[0]
    assert argv[:6] == ["taskset", "-c", "3,5", "nice", "-n", "10"]
    assert argv[6:8] == ["ffmpeg", "-hide_banner"]
    assert "testsrc=size=1920x1080:rate=30" in argv
    assert kwargs["timeout"] <= 60


@pytest.mark.parametrize("cpus", ["", "a", "0;rm", "1,2 $USER", "-1", "1,"])
def test_bad_cpu_affinity_is_refused_before_running(cpus):
    with pytest.raises(ValueError):
        low_end_probe.measure(cpus, runner=lambda *_a, **_k: None,
                              which=lambda name: name)


def test_missing_executable_fails_without_running():
    calls = []
    with pytest.raises(OSError, match="ffmpeg"):
        low_end_probe.measure(runner=lambda *_a, **_k: calls.append(1),
                              which=lambda name: None if name == "ffmpeg" else name)
    assert calls == []


def test_failed_encoder_never_counts_a_partial_progress_report_as_success():
    def run(_argv, **_kwargs):
        return SimpleNamespace(returncode=1, stderr="frame=12 fps= 99.0")
    result = low_end_probe.measure(runner=run, which=lambda name: name)
    assert result["measured_fps"] is None
    assert result["recommended_tier"] == "saver"
    assert result["measured_speed_x"] is None
