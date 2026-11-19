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
    (153, "fix/dlna-discovery-budget-20261118", "59a5e303d97825713e5884a0abe8222f739cba23"),
    (154, "fix/motion-video-artwork-20261118", "47b7eb2495b3c62ffaf78646d7d291afc76ddc67"),
    (155, "fix/rotated-video-geometry-v2-20261118", "d78853dbec8d0708f951162d44681aeff9bc421c"),
    (156, "fix/screenshot-source-clock-20261118", "5d18ca213ade2683b6b017995cb9a30b6bf209e1"),
    (157, "fix/msys2-private-download-20261118", "dfb3ef8ee0ee5c4c03b5aea8639a41518aa6077f"),
    (158, "fix/sc-094-persist-native-runtime", "698e0f4f7fc9e7f05bd378af660945fb15e199e8"),
    (159, "fix/sc-128-window-geometry-persistence", "233fabef00ea8cb460de79cbc5c7fc4d0595fc29"),
    (160, "fix/sc-053-lock-target-change", "9ba9407f3b650947e58372378c050a0f20fb4e39"),
    (162, "fix/sc-058-verified-hls-adoption", "dcf6e09400fa8c03f14782ebd28889476296a610"),
    (163, "fix/sc-009-serialize-transport", "48beae5efd0d27717dc2f470a085d771835c9e4f"),
    (164, "fix/sc-018-venv-rollback", "f0bd7cbfb03d2d398cd76538f96a1a099feb2a17"),
    (165, "fix/sc-008-preserve-discovered-identity", "6b8bee74581d30ed141d3a4978f8362ec879cdd3"),
    (166, "fix/sc-010-bounded-playback-watchdog", "144386f5d671acf0f5bd3582b756ebb3bbafeb2d"),
    (167, "fix/sc-012-reliable-ffmpeg-ci", "e2fc31c8a5aac313880a8c37ab16f5c60851c2b7"),
    (168, "fix/sc-011-direct-receiver-confirmation", "b3091e6b8c19257a70e48b99b05b0885f91a739b"),
    (173, "fix/sc-097-installed-artifact", "81e84ae1b5a70eea74c00676b3d7663cbcc327d0"),
    (174, "fix/sc-007-network-route-diagnostics", "9c8e78bf0eeb0dff043364b6358b80a441d97b1f"),
    (175, "fix/sc-015-preserve-restart-subtitles", "9190ed9a2ebfc2805cb38bb35378bcf85b78f227"),
    (176, "fix/sc-043-ship-cast-targets", "85f9f829b99ba2fc9d1159e5f089979a67b3a49f"),
    (177, "fix/sc-062-distinct-hls-generations", "a191ce974d83f51747442a0df8659d104ca99ec0"),
    (186, "fix/sc-049-subtitle-input-sandbox", "fc0a8e7fdca3f274cd149aa2c4137edbd7446064"),
    (188, "fix/p0-14-gui-route-check", "928edfe7b1bbcb871962beaa660a108d7ebbfa14"),
    (189, "fix/p0-13-preflight-retains-live-session", "46b37871855c9b7fa1c77964bf23528fc27fda8a"),
    (190, "agent/issue-59-release-qualification", "5b99724c2c0ab1a18869864fe1f74c7da2581400"),
    (193, "agent/issue-53-local-library-index", "b1bb8ade582087f1326bd0a7f917ad9902c216c1"),
    (198, "fix/194-validated-worker-domains", "6c9d51abacd17ea78101dc9f8595d09661fa9262"),
    (199, "fix/sc-064-preflight-motion-index-20261119", "95a7ca6c86bf6c8a1f08d9ce14acaa76265727fe"),
    (200, "fix/sc-074-paused-restart-timeline-20261119", "04a1f243dd02b317e4b3da8efaf75976e50a0121"),
    (220, "fix/sc-061-hls-pause-rollover-20261119", "5406a47ae5e4bf3c13f1b9a77b7bfe0e9cd3a2d8"),
    (222, "docs/develop-branch-model", "e02a3ed36e15b2b048d11336b02c57355c333874"),
    (224, "fix/223-library-ctime-test-portability", "59bc5814707967e296eff24d1f8267fd3f7aa96b"),
    (225, "integrate/191-preferences-current", "21dabbb823b83af571d89200f9f3d93ced47be3f"),
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


def github_open_pr_refs(token: str | None = None) -> set[tuple[str, str]]:
    """Fail closed unless all currently open same-repository heads are known."""
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    heads: set[tuple[str, str]] = set()
    for page in range(1, 12):
        url = (f"https://api.github.com/repos/{REPOSITORY}/pulls"
               f"?state=open&per_page=100&page={page}")
        with urlopen(Request(url, headers=headers), timeout=12) as response:
            records = json.load(response)
        if not isinstance(records, list):
            raise ValueError("Could not validate open PR branch inventory")
        for pr in records:
            head = pr.get("head") or {}
            repo = head.get("repo") or {}
            if repo.get("full_name") == REPOSITORY:
                heads.add((REPOSITORY, head.get("ref")))
        if len(records) < 100:
            return heads
    raise RuntimeError("Open PR inventory exceeded the bounded page limit")


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
          fetch=github_pr, git=run_git, apply: bool = False,
          open_refs: set[tuple[str, str]] | None = None) -> str:
    """Return READY/DELETED/SKIP; never attempt to delete unmerged/changed refs."""
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        return "SKIP invalid PR"
    if not _safe_branch(branch) or not isinstance(expected, str) or not SHA.fullmatch(expected):
        return "SKIP unsafe ref"
    if open_refs is not None and (REPOSITORY, branch) in open_refs:
        return f"SKIP {branch}: still used by another open PR"
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
    open_refs = github_open_pr_refs(token)
    failures = 0
    for number, branch, sha in event_candidates(opts.event, payload):
        try:
            outcome = prune(number, branch, sha, fetch=lambda n: github_pr(n, token),
                            apply=opts.apply, open_refs=open_refs)
            print(outcome, flush=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"ERROR {branch}: {type(exc).__name__}", flush=True)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
