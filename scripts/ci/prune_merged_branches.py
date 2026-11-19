#!/usr/bin/env python3
"""Delete only immutable, confirmed merged PR source refs, with a Git lease.

The default is an auditable dry run. A trusted develop workflow passes --apply;
this module never needs a GitHub App administration permission or a shell.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

REPOSITORY = "gmanldn/smoothcast"
PROTECTED = frozenset({"main", "develop", "test"})
# Recorded merged PR head SHAs, verified again against the GitHub PR and remote
# before deletion. A branch that advanced after merge MUST remain untouched.
BACKFILL = (
    (198, "fix/194-validated-worker-domains", "6c9d51abacd17ea78101dc9f8595d09661fa9262"),
    (199, "fix/sc-064-preflight-motion-index-20261119", "95a7ca6c86bf6c8a1f08d9ce14acaa76265727fe"),
    (200, "fix/sc-074-paused-restart-timeline-20261119", "04a1f243dd02b317e4b3da8efaf75976e50a0121"),
    (222, "docs/develop-branch-model", "e02a3ed36e15b2b048d11336b02c57355c333874"),
    (224, "fix/223-library-ctime-test-portability", "59bc5814707967e296eff24d1f8267fd3f7aa96b"),
    (189, "fix/p0-13-preflight-retains-live-session", "46b37871855c9b7fa1c77964bf23528fc27fda8a"),
    (186, "fix/sc-049-subtitle-input-sandbox", "fc0a8e7fdca3f274cd149aa2c4137edbd7446064"),
    (220, "fix/sc-061-hls-pause-rollover-20261119", "5406a47ae5e4bf3c13f1b9a77b7bfe0e9cd3a2d8"),
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")


def _safe_branch(name: str) -> bool:
    return bool(
        isinstance(name, str) and BRANCH.fullmatch(name)
        and name not in PROTECTED and not name.startswith(("release/", "refs/"))
        and ".." not in name and "//" not in name and "@{" not in name
        and not name.endswith(("/", ".", ".lock"))
    )


def github_pr(number: int, token: str | None = None, repository: str = REPOSITORY) -> dict:
    """Read-only official GitHub REST call, bounded by a network timeout."""
    url = f"https://api.github.com/repos/{repository}/pulls/{int(number)}"
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=12) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Invalid GitHub PR response")
    return data


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, timeout=30,
    )
    return result.stdout


def event_candidates(event_name: str, event: dict | None) -> tuple:
    """Only post-merge develop events can request automatic source pruning."""
    if event_name == "pull_request":
        pr = (event or {}).get("pull_request") or {}
        if not pr.get("merged") or (pr.get("base") or {}).get("ref") != "develop":
            return ()
        head = pr.get("head") or {}
        return ((pr.get("number"), head.get("ref"), head.get("sha")),)
    if event_name in {"push", "backfill"}:
        return BACKFILL
    return ()


def prune(number: int, branch: str, expected: str, *,
          fetch=github_pr, git=run_git, apply: bool = False) -> str:
    """Return READY/DELETED/SKIP; never attempt to delete unmerged/changed refs."""
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        return "SKIP invalid PR"
    if not _safe_branch(branch) or not isinstance(expected, str) or not SHA.fullmatch(expected):
        return "SKIP unsafe ref"
    pr = fetch(number)
    head = pr.get("head") or {}
    src = head.get("repo") or {}
    if (
        not pr.get("merged_at") or pr.get("merged") is False
        or src.get("full_name") != REPOSITORY or head.get("ref") != branch
        or head.get("sha") != expected
        or (pr.get("base") or {}).get("ref") not in {"develop", "main"}
    ):
        return f"SKIP {branch}: PR identity/merge/head changed"
    ref = f"refs/heads/{branch}"
    rows = git("ls-remote", "--heads", "origin", ref).strip().splitlines()
    if not rows:
        return f"SKIP {branch}: already absent"
    fields = rows[0].split()
    if len(rows) != 1 or len(fields) != 2 or fields[1] != ref or fields[0] != expected:
        return f"SKIP {branch}: remote ref advanced or mismatched"
    if not apply:
        return f"READY {branch}: {expected}"
    # Server-side atomic compare-and-delete; a concurrent update is preserved.
    git("push", "--porcelain", f"--force-with-lease={ref}:{expected}", "origin", f":{ref}")
    return f"DELETED {branch}: {expected}"


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply", action="store_true", help="Delete confirmed merged refs (dry run otherwise)")
    args.add_argument("--event", choices=("backfill", "push", "pull_request"),
                      default=os.getenv("GITHUB_EVENT_NAME", "backfill"))
    args.add_argument("--event-file", type=Path,
                      default=Path(os.getenv("GITHUB_EVENT_PATH") or "/dev/null"))
    opts = args.parse_args(argv)
    remote = run_git("remote", "get-url", "origin").strip()
    if not re.search(r"github\.com[:/]gmanldn/smoothcast(?:\.git)?/?\Z", remote, re.I):
        raise RuntimeError("Refusing to operate outside the expected repository")
    payload = {}
    if opts.event == "pull_request":
        payload = json.loads(opts.event_file.read_text(encoding="utf-8"))
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    failures = 0
    for number, branch, sha in event_candidates(opts.event, payload):
        try:
            outcome = prune(number, branch, sha, fetch=lambda n: github_pr(n, token),
                            apply=opts.apply)
            print(outcome, flush=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"ERROR {branch}: {type(exc).__name__}", flush=True)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
