#!/usr/bin/env python3
"""Fail-closed version-history guard for direct multi-agent pushes to develop.

Check every commit in a push, including commits earlier than the pushed HEAD:
    python3 scripts/ci/check_version_history.py --before <old> --after <new>

The guard is read-only. It never assigns a version, rewrites history, promotes
main, launches the app, or contacts receivers.  It verifies first-parent
transitions; merge commits may not silently replace the inherited version.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys

VERSION_FILE = "src/version.py"
ZERO = "0" * 40
_SHA = re.compile(r"[a-fA-F0-9]{40,64}\Z")


class VersionHistoryError(ValueError):
    """An invalid or unsafe release-number transition."""


def parse_version(source: str) -> tuple[int, int, int]:
    """Read exactly one literal assignment per component, without executing code."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise VersionHistoryError("invalid version.py syntax") from exc
    parts: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in ("MAJOR", "MINOR", "PATCH"):
            continue
        if target.id in parts or not isinstance(node.value, ast.Constant):
            raise VersionHistoryError("duplicate or non-literal version component")
        value = node.value.value
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise VersionHistoryError("version components must be non-negative bounded integers")
        parts[target.id] = value
    if set(parts) != {"MAJOR", "MINOR", "PATCH"}:
        raise VersionHistoryError("version components missing")
    return parts["MAJOR"], parts["MINOR"], parts["PATCH"]


def valid_transition(before: tuple[int, int, int], after: tuple[int, int, int]) -> bool:
    major, minor, patch = before
    return after in ((major, minor, patch), (major, minor, patch + 1),
                     (major, minor + 1, 0), (major + 1, 0, 0))


def git(*args: str, missing_ok: bool = False) -> str | None:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if proc.returncode:
        if missing_ok:
            return None
        raise VersionHistoryError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:240]}")
    return proc.stdout.strip()


def revision_version(rev: str) -> tuple[int, int, int]:
    source = git("show", f"{rev}:{VERSION_FILE}")
    assert source is not None
    return parse_version(source)


def check_range(before: str, after: str) -> int:
    if not _SHA.fullmatch(after) or not _SHA.fullmatch(before):
        raise VersionHistoryError("refs must be full Git SHAs")
    if before == ZERO:
        # For initial branch creation, the whole reachable history may predate
        # the guard. Check the tip against its immediate first parent instead.
        commits = [after]
    else:
        git("merge-base", "--is-ancestor", before, after)
        raw = git("rev-list", "--reverse", "--topo-order", f"{before}..{after}")
        commits = raw.splitlines() if raw else []
    checked = 0
    for commit in commits:
        parents = (git("rev-list", "--parents", "-n", "1", commit) or "").split()[1:]
        if not parents:
            revision_version(commit)
            checked += 1
            continue
        previous, current = revision_version(parents[0]), revision_version(commit)
        if not valid_transition(previous, current):
            raise VersionHistoryError(
                f"{commit[:12]} changes {previous} -> {current}; "
                "only unchanged, +1 PATCH, +1 MINOR (reset PATCH), "
                "or +1 MAJOR (reset MINOR/PATCH) are permitted"
            )
        # A merge must not discard a version already present in a second parent.
        for extra in parents[1:]:
            incoming = revision_version(extra)
            if current < incoming:
                raise VersionHistoryError(
                    f"{commit[:12]} merges version {incoming} but resolves to {current}"
                )
        checked += 1
    return checked


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    args = p.parse_args(argv)
    try:
        checked = check_range(args.before, args.after)
    except VersionHistoryError as exc:
        print(f"VERSION HISTORY INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"version history OK: {checked} commit(s) inspected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
