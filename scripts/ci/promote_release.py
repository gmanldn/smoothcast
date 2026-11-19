"""Decide whether a verified ``develop`` commit is a new release for ``main``.

SmoothCast integrates on ``develop``; ``main`` only ever receives released
code. When ``src/version.py`` on a *verified* develop commit is newer than the
version on ``main``, the verify workflow opens and merges a develop -> main
pull request. This script holds the safety decision so it can be unit tested:

* the develop version must be strictly greater than main's (no re-release,
  never a downgrade);
* merging develop into main must produce exactly develop's tree. If main holds
  content develop does not (a stray hotfix), promotion is refused rather than
  silently mixing histories.

Exit status: 0 promote, 10 nothing to promote (same or older version),
1 refuse (divergence or unreadable version). CI treats 10 as success.

Usage: python3 scripts/ci/promote_release.py check SHA [--main origin/main]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NOTHING_TO_PROMOTE = 10
_PART = re.compile(r"^(MAJOR|MINOR|PATCH)\s*=\s*(\d+)\s*$", re.MULTILINE)


class PromoteError(Exception):
    """Promotion is unsafe; nothing must be merged."""


def parse_version(source: str) -> tuple[int, int, int]:
    """Read MAJOR/MINOR/PATCH from version.py text without executing it."""
    parts = {name: int(value) for name, value in _PART.findall(source)}
    if set(parts) != {"MAJOR", "MINOR", "PATCH"}:
        raise PromoteError("cannot read MAJOR.MINOR.PATCH from src/version.py")
    return parts["MAJOR"], parts["MINOR"], parts["PATCH"]


def label(version: tuple[int, int, int]) -> str:
    return "v{}.{}.{}".format(*version)


def needs_promotion(develop: tuple[int, int, int], main: tuple[int, int, int]) -> bool:
    return develop > main


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PromoteError(f"git {args[0]} could not run: {exc}") from exc
    if result.returncode != 0:
        raise PromoteError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def merge_is_clean_fast_forward_of_content(repo: Path, sha: str, main: str) -> bool:
    """True if merging *sha* into *main* yields exactly *sha*'s tree."""
    merged = _git(repo, "merge-tree", "--write-tree", main, sha).splitlines()[0]
    return merged == _git(repo, "rev-parse", f"{sha}^{{tree}}")


def decide(repo: Path, sha: str, main: str = "origin/main") -> str:
    """Return the tag to release, or raise PromoteError / return '' if none."""
    develop_v = parse_version(_git(repo, "show", f"{sha}:src/version.py"))
    main_v = parse_version(_git(repo, "show", f"{main}:src/version.py"))
    if not needs_promotion(develop_v, main_v):
        return ""
    try:
        clean = merge_is_clean_fast_forward_of_content(repo, sha, main)
    except PromoteError as exc:
        raise PromoteError(f"develop cannot merge cleanly into main: {exc}") from exc
    if not clean:
        raise PromoteError(
            "main holds changes that develop does not; reconcile by merging main into "
            "develop first. Refusing to promote.")
    return label(develop_v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("sha")
    check.add_argument("--main", default="origin/main")
    check.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        tag = decide(args.repo, args.sha, args.main)
    except PromoteError as exc:
        print(f"promotion refused: {exc}", file=sys.stderr)
        return 1
    if not tag:
        print("no new version to promote")
        return NOTHING_TO_PROMOTE
    print(tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
