"""Live control-latency gate (#466): real portal, 1/8/32 phones, fake receiver.

Opt-in (``SMOOTHCAST_PERF=1``); CI runs it serially in the search-performance job
with ``SMOOTHCAST_PERF_SLACK=3``. Compared against docs/control-latency-baseline.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import control_latency_benchmark as clb

pytestmark = [pytest.mark.perf, pytest.mark.skipif(
    not os.environ.get("SMOOTHCAST_PERF"), reason="performance gates run with SMOOTHCAST_PERF=1")]
SLACK = float(os.environ.get("SMOOTHCAST_PERF_SLACK") or 1.0)


def test_control_latency_meets_the_slos_and_the_baseline():
    baseline = json.loads((ROOT / "docs/control-latency-baseline.json").read_text(encoding="utf-8"))
    report, problems = clb.run_checked([1, 8, 32], 12, baseline, slack=SLACK)   # a breach must reproduce
    print("\n" + clb.table(report))
    assert problems == []
