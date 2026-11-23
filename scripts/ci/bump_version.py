"""Bump the authoritative version for a completed ticket or explicit release.

    python3 scripts/ci/bump_version.py patch --issue 541 --expect 1.2.25

Print only X.Y.Z to stdout for existing callers. --expect refuses stale
checkouts; a non-force fast-forward Git push remains the branch-level guard.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "src" / "version.py"
_PART = re.compile(r"^(MAJOR|MINOR|PATCH)(\s*=\s*)(\d+)(\s*)$", re.MULTILINE)


def current_version(source: str) -> str:
    """Parse a uniquely defined source version without executing code."""
    found = {m.group(1): int(m.group(3)) for m in _PART.finditer(source)}
    if set(found) != {"MAJOR", "MINOR", "PATCH"} or len(_PART.findall(source)) != 3:
        raise ValueError("expected exactly one MAJOR, MINOR and PATCH assignment")
    return f"{found['MAJOR']}.{found['MINOR']}.{found['PATCH']}"


def bump(source: str, kind: str = "patch") -> tuple[str, str]:
    """Return (updated text, X.Y.Z); reject malformed versions."""
    if kind not in {"patch", "minor", "major"}:
        raise ValueError(f"unknown bump kind {kind!r}")
    major, minor, patch = (int(part) for part in current_version(source).split("."))
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new = {"MAJOR": major, "MINOR": minor, "PATCH": patch}
    text = _PART.sub(lambda m: f"{m.group(1)}{m.group(2)}{new[m.group(1)]}{m.group(4)}", source)
    return text, f"{major}.{minor}.{patch}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", nargs="?", default="patch", choices=["patch", "minor", "major"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--issue", type=int, metavar="N",
                        help="completed GitHub issue number for the commit reference")
    parser.add_argument("--expect", metavar="X.Y.Z",
                        help="fail rather than write if the checkout version differs")
    args = parser.parse_args(argv)
    try:
        if args.issue is not None and args.issue <= 0:
            raise ValueError("--issue must be a positive GitHub issue number")
        source = args.file.read_text(encoding="utf-8")
        existing = current_version(source)
        if args.expect is not None and existing != args.expect:
            raise ValueError(
                f"stale version: expected {args.expect}, found {existing}; "
                "fetch/rebase develop and rerun"
            )
        text, version = bump(source, args.kind)
        if not args.dry_run:
            args.file.write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"bump failed: {exc}", file=sys.stderr)
        return 1
    print(version)
    if args.issue is not None:
        print(f"Commit version {version} with Refs #{args.issue}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
