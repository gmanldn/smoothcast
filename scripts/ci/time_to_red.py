"""Time-to-red (#700): minutes from a commit to the first failing CI signal on it.

Pure: takes commit times and workflow-run records (GitHub REST fields ``head_sha``,
``conclusion``, ``updated_at``) and never touches the network. A commit with no
failing run has no time-to-red (``None``), which is the good outcome.
"""
from __future__ import annotations

from datetime import datetime

BUDGET_MIN = 15.0
FAILED = frozenset({"failure", "timed_out", "startup_failure"})


def _t(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def time_to_red(commit_time: str, runs: list[dict]) -> float | None:
    start = _t(commit_time)
    ends = []
    for run in runs:
        if run.get("conclusion") in FAILED and run.get("updated_at"):
            minutes = (_t(run["updated_at"]) - start).total_seconds() / 60.0
            ends.append(max(0.0, minutes))
    return round(min(ends), 1) if ends else None


def summarise(commits: dict[str, str], runs: list[dict]) -> dict:
    """commits: sha -> commit time. Returns per-commit values, the worst, and over-budget shas."""
    by_sha: dict[str, list[dict]] = {}
    for run in runs:
        by_sha.setdefault(run.get("head_sha", ""), []).append(run)
    values = {sha: time_to_red(when, by_sha.get(sha, [])) for sha, when in commits.items()}
    red = {sha: v for sha, v in values.items() if v is not None}
    return {
        "red_commits": len(red),
        "worst_min": max(red.values()) if red else None,
        "over_budget": sorted(sha for sha, v in red.items() if v > BUDGET_MIN),
        "budget_min": BUDGET_MIN,
        "values": values,
    }
