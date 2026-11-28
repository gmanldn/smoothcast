"""Time-to-red (#700): minutes from a commit to the first failing CI signal on it.

Pure: takes commit times and workflow-run records (GitHub REST fields ``head_sha``,
``conclusion``, ``updated_at``) and never touches the network. A commit with no
failing run has no time-to-red (``None``), which is the good outcome.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import sys

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


def _read_tsv(path: str, columns: int) -> list[list[str]]:
    try:
        with open(path, encoding="utf-8") as stream:
            rows = [line.rstrip("\r\n").split("\t") for line in stream if line.strip()]
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if any(len(row) != columns for row in rows):
        raise ValueError(f"{path} must contain {columns} tab-separated columns per row")
    return rows


def _summary_from_tsv(commits_path: str, runs_path: str) -> dict:
    commit_rows = _read_tsv(commits_path, 2)
    run_rows = _read_tsv(runs_path, 4)
    commits = {sha: committed_at for sha, committed_at in commit_rows}
    runs = [
        {"head_sha": sha, "conclusion": conclusion,
         "updated_at": updated_at, "event": event}
        for sha, conclusion, updated_at, event in run_rows if event == "push"
    ]
    result = summarise(commits, runs)
    result["observed_commits"] = len(commits)
    result["observed_runs"] = len(runs)
    return result


def report(commits_path: str, runs_path: str) -> str:
    """Format a bounded GitHub Actions data export for the nightly job summary."""
    summary = _summary_from_tsv(commits_path, runs_path)
    worst = "not observed" if summary["worst_min"] is None else f"{summary['worst_min']:.1f} min"
    over = ", ".join(sha[:12] for sha in summary["over_budget"]) or "none"
    return "\n".join((
        "### Develop time-to-red",
        f"Observed {summary['observed_commits']} recent commits and "
        f"{summary['observed_runs']} push workflow runs "
        "from the first API page (at most 100 records each).",
        f"First completed failing signal: {summary['red_commits']} commits; worst: {worst}.",
        f"Over the {BUDGET_MIN:.0f} minute budget: {over}.",
        "This bounded sample is diagnostic; no observed failure does not qualify a commit.",
        "",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commits-tsv", required=True,
                        help="SHA and committer timestamp, one tab-separated row per commit")
    parser.add_argument("--runs-tsv", required=True,
                        help="head SHA, conclusion, updated timestamp, event per run")
    args = parser.parse_args(argv)
    try:
        summary = _summary_from_tsv(args.commits_tsv, args.runs_tsv)
        print(report(args.commits_tsv, args.runs_tsv), end="")
    except (ValueError, TypeError) as exc:
        print(f"time-to-red report unavailable: {exc}", file=sys.stderr)
        return 2
    return 1 if summary["over_budget"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
