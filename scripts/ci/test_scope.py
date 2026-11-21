"""Choose the fast or full verification lane for a develop push.

Patch-only progress (and commits that do not bump ``src/version.py``) takes the
fast lane: lint, type checking, and syntax compilation. A MINOR or MAJOR version
bump takes the full lane: the portable suite, native runners, media integration,
setup contracts, and installed-artifact checks.

CI runs this before scheduling the expensive jobs and applies the same policy
locally. Missing/unreadable history fails closed to ``full``.

Usage: python3 scripts/ci/test_scope.py --base <ref> [--head <ref>]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
_VERSION = re.compile(r"^(MAJOR|MINOR|PATCH)\s*=\s*(\d+)\s*$", re.MULTILINE)
Version = tuple[int, int, int]


def read_version(text: str) -> Version | None:
    parts = {name: int(value) for name, value in _VERSION.findall(text)}
    if set(parts) != {"MAJOR", "MINOR", "PATCH"}:
        return None
    return parts["MAJOR"], parts["MINOR"], parts["PATCH"]


def classify(base: Version | None, head: Version | None) -> str:
    """Return ``fast`` for patch progress, ``full`` for minor/major or unknown."""
    if base is None or head is None:
        return "full"
    if head < base:
        return "full"
    if head[0] > base[0] or head[1] > base[1]:
        return "full"
    return "fast"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def version_at(repo: Path, ref: str) -> Version | None:
    if not ref or set(ref) == {"0"}:
        return None
    try:
        return read_version(_git(repo, "show", f"{ref}:src/version.py"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def lane(repo: Path, base: str, head: str) -> tuple[str, str]:
    base_version = version_at(repo, base)
    head_version = version_at(repo, head)
    result = classify(base_version, head_version)
    if base_version is None or head_version is None:
        reason = "version history unavailable; using the full lane"
    elif result == "full" and head_version < base_version:
        reason = "version moved backwards; using the full lane"
    elif result == "full":
        reason = f"{base_version} -> {head_version}: minor or major bump"
    else:
        reason = f"{base_version} -> {head_version}: patch-only progress"
    return result, reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="", help="previous commit or branch")
    parser.add_argument("--head", default="HEAD", help="commit under test")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    result, reason = lane(args.repo, args.base, args.head)
    print(result)
    print(reason, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())