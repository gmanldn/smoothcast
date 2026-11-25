#!/usr/bin/env python3
"""Fail-closed version-history guard for direct multi-agent pushes to develop.

Check every commit in a push, including commits earlier than the pushed HEAD:
    python3 scripts/ci/check_version_history.py --before <old> --after <new>

The guard is read-only. It never assigns a version, rewrites history, promotes
main, launches the app, or contacts receivers.  It verifies first-parent
transitions; merge commits may not silently replace the inherited version.
New ticket PATCH assignments must be unique across all reachable history.
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
    canonical_names = {"MAJOR", "MINOR", "PATCH"}
    # Record the *specific* permitted target nodes, then inspect the entire
    # AST for any other write. Otherwise PATCH += 1, a nested assignment,
    # or a walrus binding silently changes runtime SemVer without changing
    # the number recorded by this history guard.
    permitted: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in canonical_names:
            continue
        if target.id in parts or not isinstance(node.value, ast.Constant):
            raise VersionHistoryError("duplicate or non-literal version component")
        value = node.value.value
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise VersionHistoryError("version components must be non-negative bounded integers")
        parts[target.id] = value
        permitted.add(id(target))
    if set(parts) != canonical_names:
        raise VersionHistoryError("version components missing")
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id in canonical_names
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and id(node) not in permitted):
            raise VersionHistoryError(f"unexpected secondary write to {node.id}")
    # Function/class/import definitions can also rebind a canonical module
    # attribute without generating an ast.Name(Store) node.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in canonical_names:
                raise VersionHistoryError(f"unexpected shadow definition of {node.name}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if bound in canonical_names:
                    raise VersionHistoryError(f"unexpected imported binding {bound}")
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


_PATCH_SUBJECT = re.compile(
    r"chore\(version\): PATCH(?: ([0-9]+\.[0-9]+\.[0-9]+))?"
    r" for issue #([1-9][0-9]*)(?: \[sc-auto-patch\])?"
)
_PATCH_LINE = re.compile(r"^(PATCH[ \t]*=[ \t]*)[0-9]+([ \t]*)$", re.MULTILINE)


def patch_attribution(subject: str, *, strict: bool = True) -> tuple[str, str | None] | None:
    """Recognise native, connector and numbered historical assignment subjects."""
    match = _PATCH_SUBJECT.fullmatch(subject)
    if match:
        return match[2], match[1]
    if strict and subject.startswith("chore(version): PATCH") and " for issue #" in subject:
        raise VersionHistoryError("malformed ticket PATCH attribution")
    return None


def prior_assignments(roots: list[str]) -> dict[str, str]:
    """Reserve existing ticket IDs, including immutable historical duplicates."""
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise VersionHistoryError("complete history required for ticket PATCH attribution")
    if not roots:
        return {}
    rows = git("log", "--format=%H%x09%s", "--fixed-strings",
               "--grep=chore(version): PATCH", *roots, "--") or ""
    seen: dict[str, str] = {}
    for row in rows.splitlines():
        sha, sep, subject = row.partition("\t")
        if not sep or not _SHA.fullmatch(sha):
            raise VersionHistoryError("incomplete ticket PATCH history")
        assignment = patch_attribution(subject, strict=False)
        if assignment:
            seen.setdefault(assignment[0], sha)
    return seen


def check_assignment(commit: str, parents: list[str], issue: str,
                     declared: str | None, seen: dict[str, str]) -> None:
    if issue in seen:
        raise VersionHistoryError(
            f"{commit[:12]} duplicate PATCH attribution for issue #{issue}; "
            f"already assigned at {seen[issue][:12]}")
    if len(parents) != 1:
        raise VersionHistoryError("ticket PATCH must have exactly one parent")
    parent = parents[0]
    changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", commit)
    if changed != VERSION_FILE:
        raise VersionHistoryError("ticket PATCH must change only version.py")
    old = git("show", f"{parent}:{VERSION_FILE}")
    new = git("show", f"{commit}:{VERSION_FILE}")
    assert old is not None and new is not None
    major, minor, patch = parse_version(old)
    actual = parse_version(new)
    expected = _PATCH_LINE.sub(
        lambda m: m[1] + str(patch + 1) + m[2], old, count=1)
    if actual != (major, minor, patch + 1) or new != expected:
        raise VersionHistoryError("ticket PATCH must be an exact one-step version edit")
    if declared is not None and declared != ".".join(map(str, actual)):
        raise VersionHistoryError("ticket PATCH subject/version mismatch")
    seen[issue] = commit


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
    seen: dict[str, str] | None = None
    for commit in commits:
        parents = (git("rev-list", "--parents", "-n", "1", commit) or "").split()[1:]
        assignment = patch_attribution(git("show", "-s", "--format=%s", commit) or "")
        if assignment:
            if seen is None:
                seen = prior_assignments(parents if before == ZERO else [before])
            check_assignment(commit, parents, *assignment, seen)
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
