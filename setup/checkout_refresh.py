"""Refresh a registered installation from an explicitly launched local develop checkout.

Never fetch, downgrade, update a live Linux GUI or execute version-file content.
The installer owns copying, dependency checks, and rollback.
"""
from __future__ import annotations

import ast
import json
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
            raw = stream.read(129)
        if len(raw) > 128:
            return None
        lines = raw.decode("ascii").splitlines()
        value = lines[0].strip().lower() if lines else ""
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) else None


def installed_source(root: Path) -> Path | None:
    """Resolve the installer-recorded local checkout; never discover arbitrary repos."""
    marker = root / "src" / install_location.SOURCE_MARKER
    try:
        if marker.is_symlink() or not marker.is_file():
            return None
        with marker.open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return None
        value = json.loads(raw)
        if not isinstance(value, str) or not value or "\x00" in value:
            return None
        source = Path(value)
        if not source.is_absolute():
            return None
        source = source.resolve()
        destination = root.resolve()
        if (source == destination or source in destination.parents
                or destination in source.parents or not (source / ".git").exists()
                or not (source / "setup" / "bootstrap.py").is_file()
                or 'name = "smoothcast"' not in
                (source / "pyproject.toml").read_text(encoding="utf-8")):
            return None
        return source
    except (OSError, ValueError, RuntimeError, UnicodeError):
        return None


def git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=8,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def announce(version: tuple[int, int, int], revision: str | None, reason: str) -> None:
    label = "v" + ".".join(map(str, version))
    build = f" (build {revision[:12]})" if revision else " (build unknown)"
    print(f"SmoothCast: {reason} {label}{build}; remote freshness not checked.",
          file=sys.stderr, flush=True)


def refresh(root: Path, installed: Path, target: str, running) -> int:
    """Return zero when handoff can proceed; a skipped refresh loads the installed build."""
    source_version = read_version(root)
    installed_version = read_version(installed)
    if source_version is None or installed_version is None:
        print("SmoothCast: cannot establish checkout/installed version; rerun setup.",
              file=sys.stderr)
        return 1
    previous = installed_revision(installed)
    if source_version < installed_version:
        announce(installed_version, previous, "Loading newer installed version")
        return 0  # An old checkout must never downgrade a newer installation.
    # ZIP downloads have no Git metadata. Do not invoke Git (including a
    # parent's unrelated checkout), or refuse a repeat launch solely for that.
    # An archive cannot prove ancestry, so keep the registered installation.
    if not (root / ".git").exists():
        if source_version > installed_version:
            print("SmoothCast: this archive is newer than the registered install; "
                  "explicit setup is needed to replace it.", file=sys.stderr, flush=True)
        announce(installed_version, previous,
                 "Loading registered installation; archive source revision unverified")
        return 0
    head = git(root, "rev-parse", "--verify", "HEAD")
    revision = head.stdout.strip() if head is not None and head.returncode == 0 else None
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    on_develop = (branch is not None and branch.returncode == 0
                  and branch.stdout.strip() == "develop")
    # A local tracking ref is not a live remote check. A checkout that is
    # behind it is still usable, so never refuse to start over it; only skip
    # the automatic refresh and load the installed build.
    if source_version == installed_version and previous and previous == revision:
        announce(installed_version, previous, "Loading latest checked-out version")
        return 0
    # If the installed revision is newer on the same lineage, retain it.
    if source_version == installed_version and previous and revision:
        newer = git(root, "merge-base", "--is-ancestor", revision, previous)
        if newer is not None and newer.returncode == 0:
            announce(installed_version, previous, "Loading newer installed build")
            return 0
    clean = install_location._clean_source_revision(root)
    if not clean or clean != revision or not on_develop:
        print("SmoothCast: local checkout cannot be installed automatically; "
              "loading the installed build. Commit or stash changes and pull develop, "
              "then rerun to update.", file=sys.stderr)
        announce(installed_version, previous, "Loading installed version")
        return 0
    if previous:
        # A higher version number alone cannot authorise an unrelated build.
        forward = git(root, "merge-base", "--is-ancestor", previous, clean)
        if forward is None or forward.returncode != 0:
            print("SmoothCast: cannot prove a forward build update; loading the installed "
                  "build. Run setup explicitly to replace it.", file=sys.stderr)
            announce(installed_version, previous, "Loading installed version")
            return 0
    # Linux /proc provides the existing launcher with cross-install GUI discovery.
    # Do not pretend that the same scan proves quiescence on macOS or Windows.
    if target != "linux" or not Path("/proc/self/cmdline").is_file():
        print("SmoothCast: newer checkout available, but automatic refresh is unavailable "
              "on this platform; loading the installed build. Quit and run the platform "
              "setup script to update the installed copy.", file=sys.stderr)
        announce(installed_version, previous, "Loading installed version")
        return 0
    pids = running()
    if pids:
        # A running primary from this exact install can still be activated.
        # Never copy over its files or start an older competing process.
        import launch

        app = installed / "src" / "cast_control.py"
        if set(pids) & set(launch.gui_instances(target=app)):
            print("SmoothCast: update deferred; activating the running installed build. "
                  "Quit normally and rerun sc.py to apply the newer checkout.",
                  file=sys.stderr, flush=True)
            return 0
        print("SmoothCast: newer checkout available. Quit the existing SmoothCast "
              "window normally, then rerun sc.py to update it.",
              file=sys.stderr)
        return 3
    print("SmoothCast: updating installed application from v"
          + ".".join(map(str, installed_version)) + " to v"
          + ".".join(map(str, source_version))
          + f" (build {clean[:12]}) from local develop.",
          file=sys.stderr, flush=True)
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
    announce(source_version, clean, "Loading latest local develop version")
    return 0
