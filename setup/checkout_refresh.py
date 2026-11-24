"""Refresh a registered installation from an explicitly launched local develop checkout.

Never fetch, downgrade, update a live Linux GUI or execute version-file content.
The installer owns copying, dependency checks, and rollback.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import sys

import install_location


def read_version(root: Path) -> tuple[int, int, int] | None:
    try:
        tree = ast.parse((root / "src" / "version.py").read_text(encoding="utf-8"))
    except (OSError, ValueError, SyntaxError):
        return None
    parts = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in ("MAJOR", "MINOR", "PATCH"):
            continue
        if (target.id in parts or not isinstance(node.value, ast.Constant)
                or type(node.value.value) is not int
                or not 0 <= node.value.value <= 2_147_483_647):
            return None
        parts[target.id] = node.value.value
    if len(parts) != 3:
        return None
    return parts["MAJOR"], parts["MINOR"], parts["PATCH"]


def installed_revision(root: Path) -> str | None:
    marker = root / "src" / install_location.BUILD_MARKER
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        with marker.open("rb") as stream:
            value = stream.read(129).decode("ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) else None


def git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=8,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def refresh(root: Path, installed: Path, target: str, running) -> int:
    """Return zero only when handoff can proceed; never fall back after failure."""
    source_version = read_version(root)
    installed_version = read_version(installed)
    if source_version is None or installed_version is None:
        print("SmoothCast: cannot establish checkout/installed version; rerun setup.",
              file=sys.stderr)
        return 1
    if source_version < installed_version:
        return 0  # An old checkout must never downgrade a newer installation.
    previous = installed_revision(installed)
    head = git(root, "rev-parse", "--verify", "HEAD")
    revision = head.stdout.strip() if head is not None and head.returncode == 0 else None
    if source_version == installed_version and previous and previous == revision:
        return 0
    # If the installed revision is newer on the same lineage, retain it.
    if source_version == installed_version and previous and revision:
        newer = git(root, "merge-base", "--is-ancestor", revision, previous)
        if newer is not None and newer.returncode == 0:
            return 0
    clean = install_location._clean_source_revision(root)
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    if (not clean or clean != revision or branch is None or branch.returncode != 0
            or branch.stdout.strip() != "develop"):
        print("SmoothCast: installed build differs; automatic refresh requires a clean "
              "develop checkout. Pull develop or run setup explicitly.", file=sys.stderr)
        return 1
    if source_version == installed_version and previous:
        forward = git(root, "merge-base", "--is-ancestor", previous, clean)
        if forward is None or forward.returncode != 0:
            print("SmoothCast: cannot prove a forward build update; run setup explicitly.",
                  file=sys.stderr)
            return 1
    # Linux /proc provides the existing launcher with cross-install GUI discovery.
    # Do not pretend that the same scan proves quiescence on macOS or Windows.
    if target != "linux" or not Path("/proc/self/cmdline").is_file():
        print("SmoothCast: newer checkout available. Quit the application and run "
              "the platform setup script to update the installed copy.", file=sys.stderr)
        return 3
    if running():
        print("SmoothCast: newer checkout available. Quit the existing SmoothCast "
              "window normally, then rerun ./smoothcast to update it.",
              file=sys.stderr)
        return 3
    print("SmoothCast: refreshing installed application from local develop "
          + ".".join(map(str, source_version)), file=sys.stderr, flush=True)
    try:
        code = subprocess.call([sys.executable, str(root / "setup" / "bootstrap.py"),
                                "--target", target, "--yes", "--install-dir", str(installed)])
    except OSError as exc:
        print(f"SmoothCast: installed refresh failed: {exc}", file=sys.stderr)
        return 1
    if code:
        return code
    if read_version(installed) != source_version or installed_revision(installed) != clean:
        print("SmoothCast: installed refresh did not verify the requested build; "
              "refusing stale startup.", file=sys.stderr)
        return 1
    return 0
