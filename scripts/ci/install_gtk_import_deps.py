#!/usr/bin/env python3
"""Install only missing native GTK import dependencies for Linux CI (#548).

Always verify the real system Python imports Gtk 4, Adw 1 and psutil.
Do not create a window, contact receivers or relax the startup import gate.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Sequence

PACKAGES = ("python3-gi", "gir1.2-gtk-4.0", "gir1.2-adw-1", "python3-psutil")
SYSTEM_PYTHON = "/usr/bin/python3"
PROBE = (
    "import gi; "
    "gi.require_version('Gtk', '4.0'); "
    "gi.require_version('Adw', '1'); "
    "from gi.repository import Gtk, Adw; "
    "import psutil"
)


def _run(command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Capture bounded diagnostics; never use a shell or stream apt output."""
    return subprocess.run(
        list(command), check=False, text=True, capture_output=True, timeout=timeout
    )


def _failure(command: str, result: subprocess.CompletedProcess[str]) -> None:
    detail = (result.stderr or result.stdout or "").strip()[-1500:]
    print(f"{command} failed (exit {result.returncode}): {detail}", file=sys.stderr)


def missing_packages() -> list[str]:
    missing = []
    for package in PACKAGES:
        result = _run(
            ("dpkg-query", "--show", "-f=" + "$" + "{Status}", package),
            timeout=15,
        )
        if result.returncode != 0 or result.stdout.strip() != "install ok installed":
            missing.append(package)
    return missing


def install(missing: Sequence[str]) -> bool:
    """Try cached package indexes, refresh once only if the install fails."""
    if not missing:
        print("GTK dependencies: all four packages already installed; apt skipped")
        return True
    command = ["sudo", "apt-get", "install", "-y", "-qq",
               "--no-install-recommends", *missing]
    result = _run(command, timeout=180)
    if result.returncode == 0:
        print("GTK dependencies: installed missing packages without apt update")
        return True
    _failure("first apt install", result)
    print("GTK dependencies: refreshing apt indexes once, then retrying")
    updated = _run(("sudo", "apt-get", "update", "-qq"), timeout=120)
    if updated.returncode != 0:
        _failure("apt update", updated)
        return False
    retry = _run(command, timeout=180)
    if retry.returncode != 0:
        _failure("retry apt install", retry)
        return False
    print("GTK dependencies: installed missing packages after apt refresh")
    return True


def main() -> int:
    try:
        missing = missing_packages()
        if not install(missing):
            return 1
        # This is an import-only preflight: not a Gtk.Application or window.
        check = _run((SYSTEM_PYTHON, "-c", PROBE), timeout=30)
        if check.returncode != 0:
            _failure("system Python GTK/Adw/psutil import", check)
            return 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"GTK dependency setup failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    print("GTK import preflight passed; running actual startup import gate next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
