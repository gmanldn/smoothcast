"""The per-tier time report accumulates call durations by tier (#699)."""
import conftest


class _Report:
    when = "call"
    duration = 1.5
    keywords = {"unit": 1}


def test_report_accumulates_by_tier():
    conftest._TIER_SECONDS.clear()
    conftest.pytest_runtest_logreport(_Report())
    conftest.pytest_runtest_logreport(_Report())
    assert conftest._TIER_SECONDS["unit"] == (3.0, 2)
    conftest._TIER_SECONDS.clear()
