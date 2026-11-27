"""Cross-surface freshness gate (#629): desktop ⇄ web within the 500 ms bound.

Opt-in (``SMOOTHCAST_PERF=1``); CI runs it in the search-performance job beside
the #466 control-latency gate with ``SMOOTHCAST_PERF_SLACK=3``. Compared against
docs/cross-surface-freshness-baseline.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import freshness_benchmark as fb

pytestmark = [pytest.mark.perf, pytest.mark.skipif(
    not os.environ.get("SMOOTHCAST_PERF"), reason="performance gates run with SMOOTHCAST_PERF=1")]
SLACK = float(os.environ.get("SMOOTHCAST_PERF_SLACK") or 1.0)


def test_cross_surface_freshness_meets_the_bound_and_the_baseline():
    baseline = json.loads((ROOT / "docs/cross-surface-freshness-baseline.json").read_text(encoding="utf-8"))
    report, problems = fb.run_checked(12, baseline, slack=SLACK)   # a breach must reproduce
    print("\n" + fb.table(report))
    assert problems == []
