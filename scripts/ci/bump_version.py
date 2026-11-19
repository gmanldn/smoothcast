"""Bump the single release version in src/version.py (point release by default).

    python3 scripts/ci/bump_version.py [patch|minor|major] [--dry-run] [--file PATH]

Edits only the MAJOR/MINOR/PATCH assignments and prints the new version. Run it
once, at an intentional release boundary, on develop.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "src" / "version.py"
_PART = re.compile(r"^(MAJOR|MINOR|PATCH)(\s*=\s*)(\d+)(\s*)$", re.MULTILINE)


def bump(source: str, kind: str = "patch") -> tuple[str, str]:
    """Return (new source text, new 'X.Y.Z'); raises ValueError if unreadable."""
    if kind not in {"patch", "minor", "major"}:
        raise ValueError(f"unknown bump kind {kind!r}")
    found = {m.group(1): int(m.group(3)) for m in _PART.finditer(source)}
    if set(found) != {"MAJOR", "MINOR", "PATCH"} or len(_PART.findall(source)) != 3:
        raise ValueError("expected exactly one MAJOR, MINOR and PATCH assignment")
    major, minor, patch = found["MAJOR"], found["MINOR"], found["PATCH"]
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
    args = parser.parse_args(argv)
    try:
        text, version = bump(args.file.read_text(encoding="utf-8"), args.kind)
    except (OSError, ValueError) as exc:
        print(f"bump failed: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run:
        args.file.write_text(text, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
