"""Release helpers for the tagged-release workflow (issue #257).

Pure, network-free and GTK-free so the rules are unit tested:

* ``check-tag``  — the Git tag must be exactly ``v<src/version.py version>``.
* ``checksums``  — write ``SHA256SUMS`` for the built sdist and wheel.
* ``notes``      — release notes from the commit subjects since the last tag.

Usage (from the repository root)::

    python3 scripts/ci/release_artifacts.py check-tag v1.0.58
    python3 scripts/ci/release_artifacts.py checksums dist
    python3 scripts/ci/release_artifacts.py notes v1.0.58 [--previous v1.0.57] [--ref HEAD]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import version  # noqa: E402  (src is added to the path just above)

_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")


class ReleaseError(Exception):
    """A release precondition failed; nothing must be published."""


def expected_tag(version_file: Path = ROOT / "src" / "version.py") -> str:
    declared = version.read_checkout_version(version_file)
    if declared is None:
        raise ReleaseError(f"cannot read a MAJOR.MINOR.PATCH version from {version_file}")
    return f"v{declared}"


def check_tag(tag: str, version_file: Path = ROOT / "src" / "version.py") -> str:
    """Return the bare version if *tag* matches src/version.py exactly."""
    if not _TAG.fullmatch(tag):
        raise ReleaseError(f"tag {tag!r} is not of the form vMAJOR.MINOR.PATCH")
    wanted = expected_tag(version_file)
    if tag != wanted:
        raise ReleaseError(
            f"tag {tag} does not match src/version.py ({wanted}); bump the version "
            "on develop, merge it to main, then tag that commit")
    return tag[1:]


def checksums(dist: Path) -> Path:
    """Write SHA256SUMS (sha256sum format) covering every artifact in *dist*."""
    artifacts = sorted(
        p for p in Path(dist).iterdir()
        if p.is_file() and (p.name.endswith(".whl") or p.name.endswith(".tar.gz")))
    if not any(p.suffix == ".whl" for p in artifacts) or not any(
            p.name.endswith(".tar.gz") for p in artifacts):
        raise ReleaseError(f"{dist} must contain both an sdist (.tar.gz) and a wheel (.whl)")
    lines = []
    for path in artifacts:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {path.name}")
    target = Path(dist) / "SHA256SUMS"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def notes(tag: str, previous: str | None = None, *, ref: str | None = None,
          subjects: list[str] | None = None) -> str:
    """Markdown notes: commit subjects in ``previous..ref`` (merge commits skipped).

    *ref* defaults to the tag; a dry run before tagging passes ``HEAD``.
    """
    if subjects is None:
        end = ref or tag
        span = f"{previous}..{end}" if previous else end
        try:
            out = subprocess.run(
                ["git", "log", "--no-merges", "--format=%s", span],
                cwd=ROOT, capture_output=True, text=True, check=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseError(f"cannot read git history for {span}: {exc}") from exc
        subjects = out.splitlines()
    body = "\n".join(f"- {line}" for line in subjects if line.strip()) or "- No changes recorded."
    since = f" since {previous}" if previous else ""
    return (f"# SmoothCast {tag}\n\nChanges{since}:\n\n{body}\n\n"
            "Verify downloads with `sha256sum -c SHA256SUMS`. These are Python "
            "source and wheel artifacts; CI success is not native receiver, "
            "macOS or Windows qualification (see docs/RELEASE_QUALIFICATION.md).\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-tag").add_argument("tag")
    sub.add_parser("checksums").add_argument("dist", type=Path)
    note = sub.add_parser("notes")
    note.add_argument("tag")
    note.add_argument("--previous")
    note.add_argument("--ref", help="git ref to read history from (default: the tag)")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-tag":
            print(check_tag(args.tag))
        elif args.command == "checksums":
            print(checksums(args.dist))
        else:
            print(notes(args.tag, args.previous, ref=args.ref), end="")
    except ReleaseError as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
