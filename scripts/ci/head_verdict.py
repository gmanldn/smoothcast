#!/usr/bin/env python3
"""Read-only, exact-develop-SHA GitHub Actions verdict; never closes an issue.

    python3 scripts/ci/head_verdict.py [--json] [--head SHA]

Zero exit means current develop passed all observed push workflows, including
Verify SmoothCast. Pending, deleted, changed and failed heads are never green.
No stored tokens, CI writes, GUI, daemon, or third-party Python dependencies.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any, Callable

REPOSITORY = "gmanldn/smoothcast"
VERIFY = "Verify SmoothCast"
PROMOTION = "Promote verified release to main"
REQUIRED = frozenset({
    "Test lane", "Fast syntax", "Ruff lint", "Type check (mypy)",
    "Dependency audit (pip-audit)", "Mesh protocol safety (headless)",
    "Startup import budget",
})
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class VerdictError(RuntimeError):
    """Remote data unavailable or malformed; no verification is assumed."""


def _api(path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["gh", "api", path], text=True, capture_output=True,
            timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerdictError(f"gh api unavailable: {type(exc).__name__}") from exc
    if result.returncode:
        raise VerdictError(
            f"gh api failed (exit {result.returncode}); check gh auth, "
            "repository access and the develop ref"
        )
    if len(result.stdout) > 2_000_000:
        raise VerdictError("GitHub API response exceeds 2 MB")
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise VerdictError("GitHub returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise VerdictError("GitHub returned a non-object JSON payload")
    return value


def _head(payload: dict[str, Any]) -> str:
    obj = payload.get("object")
    sha = obj.get("sha") if isinstance(obj, dict) else None
    if not isinstance(sha, str) or not SHA.fullmatch(sha.lower()):
        raise VerdictError("develop head unavailable or invalid")
    return sha.lower()


def _run_number(run: dict[str, Any]) -> tuple[int, int]:
    try:
        return int(run["id"]), int(run.get("run_attempt") or 1)
    except (KeyError, TypeError, ValueError) as exc:
        raise VerdictError("malformed GitHub Actions run identity") from exc


def _pending(conclusion: str | None, status: str) -> bool:
    return status != "completed" and conclusion is None


def inspect(
    repository: str = REPOSITORY,
    expected_sha: str | None = None,
    api: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not REPO.fullmatch(repository):
        raise VerdictError("repository must be owner/name")
    if expected_sha is not None:
        expected_sha = expected_sha.lower()
        if not SHA.fullmatch(expected_sha):
            raise VerdictError("--head must be a full 40/64-hex Git SHA")
    read = api or _api
    root = f"/repos/{repository}"
    current = _head(read(f"{root}/git/ref/heads/develop"))
    result: dict[str, Any] = {
        "repository": repository, "head": current, "run": None, "url": None,
        "software": "unknown", "release": "unknown", "verdict": "unknown",
        "software_qualified": False,
        "checks": {}, "blockers": [],
    }
    if expected_sha is not None and expected_sha != current:
        result["verdict"] = "stale"
        result["blockers"] = ["requested SHA is not the current develop head"]
        return result
    runs_payload = read(f"{root}/actions/runs?head_sha={current}&per_page=50")
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise VerdictError("GitHub Actions runs list missing")
    if len(runs) > 50 or runs_payload.get("total_count", 0) > 50:
        raise VerdictError("too many runs for one SHA: narrow the API query")
    selected = [
        item for item in runs if isinstance(item, dict)
        and item.get("head_sha") == current and item.get("event") == "push"
        and item.get("head_branch") in ("develop", None)
    ]
    verify_runs = [run for run in selected if run.get("name") == VERIFY]
    if not verify_runs:
        result["blockers"] = ["no push Verify SmoothCast run at exact develop SHA"]
        return result
    verify = max(verify_runs, key=_run_number)
    run_id = _run_number(verify)[0]
    result["run"] = run_id
    result["url"] = verify.get("html_url") or (
        f"https://github.com/{repository}/actions/runs/{run_id}"
    )
    other: dict[str, dict[str, Any]] = {}
    for run in selected:
        name = run.get("name")
        if not isinstance(name, str) or name == VERIFY:
            continue
        if name not in other or _run_number(run) > _run_number(other[name]):
            other[name] = run
    statuses = {}
    for name, workflow in sorted(other.items()):
        status = workflow.get("status")
        conclusion = workflow.get("conclusion")
        if _pending(conclusion, status):
            statuses[name] = "pending"
        elif status == "completed" and conclusion == "success":
            statuses[name] = "passed"
        else:
            statuses[name] = "failed"
    result["checks"] = statuses
    jobs_payload = read(f"{root}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 100:
        raise VerdictError("GitHub Actions job list missing or oversized")
    if jobs_payload.get("total_count", len(jobs)) > 100:
        raise VerdictError("more than 100 jobs; cannot verify all required checks")
    by_name: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise VerdictError("malformed job entry")
        name = job["name"]
        if name in by_name:
            raise VerdictError(f"ambiguous duplicate job: {name}")
        by_name[name] = job
    problems = []
    pending = []
    missing = sorted(REQUIRED - by_name.keys())
    if missing:
        pending.extend(f"missing required job: {name}" for name in missing)
    for name, job in by_name.items():
        if name == PROMOTION:
            continue
        status, conclusion = job.get("status"), job.get("conclusion")
        if _pending(conclusion, status):
            pending.append(f"{name}: pending")
        elif status == "completed" and (
            conclusion == "success" or
            (conclusion == "skipped" and name not in REQUIRED)
        ):
            continue
        else:
            problems.append(f"{name}: {conclusion or status or 'unknown'}")
    for name, state in statuses.items():
        if state == "failed":
            problems.append(f"{name}: failed")
        elif state == "pending":
            pending.append(f"{name}: pending")
    if problems:
        result["software"] = "failed"
    elif pending:
        result["software"] = "pending"
    else:
        result["software"] = "passed"
    promote = by_name.get(PROMOTION)
    if promote is None:
        result["release"] = "pending" if verify.get("status") != "completed" else "unknown"
    elif _pending(promote.get("conclusion"), promote.get("status")):
        result["release"] = "pending"
    elif promote.get("status") == "completed":
        result["release"] = {
            "success": "passed", "skipped": "not_required",
        }.get(promote.get("conclusion"), "blocked")
    if not problems and not pending and verify.get("status") == "completed" and (
        verify.get("conclusion") != "success"
        and result["release"] not in ("blocked",)
    ):
        problems.append(f"{VERIFY}: {verify.get('conclusion') or 'unknown'}")
        result["software"] = "failed"
    if result["release"] == "blocked":
        problems.append(f"{PROMOTION}: blocked")
    if result["release"] == "unknown":
        pending.append(f"{PROMOTION}: no conclusive job")
    if verify.get("status") != "completed":
        pending.append(f"{VERIFY}: not complete")
    result["blockers"] = (problems + pending)[:12]
    if problems:
        result["verdict"] = "failed"
    elif pending or result["release"] == "pending":
        result["verdict"] = "pending"
    elif result["software"] == "passed" and result["release"] in (
        "passed", "not_required"
    ) and verify.get("conclusion") == "success":
        result["verdict"] = "green"
    else:
        result["verdict"] = "unknown"
    latest = _head(read(f"{root}/git/ref/heads/develop"))
    if latest != current:
        result["verdict"] = "stale"
        result["blockers"] = [f"develop moved to {latest}; recheck current head"]
    else:
        # A protected-main policy refusal is not a failure of the validated
        # software. Never infer success from a partial run or missing checks.
        release_only_failure = (
            verify.get("conclusion") == "failure"
            and promote is not None
            and promote.get("status") == "completed"
            and promote.get("conclusion") == "failure"
            and result["release"] == "blocked"
        )
        fully_verified = (
            verify.get("conclusion") == "success"
            and result["release"] in ("passed", "not_required")
        )
        result["software_qualified"] = bool(
            result["software"] == "passed"
            and verify.get("status") == "completed"
            and (fully_verified or release_only_failure)
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--head", help="expected exact develop commit SHA")
    parser.add_argument("--json", action="store_true", help="compact machine output")
    parser.add_argument("--software-only", action="store_true",
                        help="exit zero for qualified software even if release promotion was blocked")
    args = parser.parse_args(argv)
    try:
        result = inspect(args.repo, args.head)
    except VerdictError as exc:
        print(f"CI verdict unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    else:
        print(
            f"develop {result['head'][:12]} "
            f"software={result['software']} release={result['release']} "
            f"verdict={result['verdict']} "
            f"software_qualified={str(result['software_qualified']).lower()} "
            f"run={result['run'] or '-'}"
        )
        if result["url"]:
            print(result["url"])
        for blocker in result["blockers"]:
            print(f"  - {blocker}")
    if args.software_only:
        if result["software_qualified"]:
            return 0
        return 1 if result["software"] == "failed" or result["verdict"] == "failed" else 2
    return 0 if result["verdict"] == "green" else (
        1 if result["verdict"] == "failed" else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
