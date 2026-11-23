"""Portable CI must allow the supported 3.10 suite to finish under load."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_portable_job_is_bounded_without_skipping_py310_or_py313():
    source = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
    job = source.split("  portable-tests:", 1)[1].split("  portable-tests-native:", 1)[0]
    assert "timeout-minutes: 20" in job
    assert "python-version: ['3.10', '3.13']" in job
    assert "python -m pytest -q tests" in job
    # xdist runs the whole suite in parallel; keep both matrix legs and coverage
    # while removing the serial wall-clock bottleneck.
    assert "pytest-xdist>=3,<4" in job
    assert job.count("-n auto") == 2
    assert "SMOOTHCAST_TEST_CONTEXT" in source
    assert "python -m compileall -q src scripts setup tests" in job
    assert "--ignore" not in job and "-k " not in job
