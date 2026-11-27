"""One-step owner provisioning of the reference link-acquisition launcher (#588).

Writes a tiny absolute-path wrapper around ``scripts/link_sandbox_bwrap.py`` into
the owner's config directory. Writing it is *not* trust: the provider still
advertises only after ``--link-check --qualify`` passes for this exact file, and
nothing is enabled for guests until the owner turns a provider on. GTK-free.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import sys

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "link_sandbox_bwrap.py"


def wrapper_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cast-control" / "link-sandbox"


def default_launcher() -> str:
    """The provisioned wrapper if present, executable and absolute, else ''."""
    path = wrapper_path()
    return str(path) if path.is_absolute() and path.is_file() and os.access(path, os.X_OK) else ""


def unsupported_reason() -> str:
    if not sys.platform.startswith("linux"):
        return ("the shipped reference launcher is Linux-only; this platform needs its own "
                "launcher (set SMOOTHCAST_LINK_SANDBOX) that passes 'smoothcast --link-check --qualify'")
    if not shutil.which("bwrap"):
        return "install bubblewrap (package 'bubblewrap'), then run 'smoothcast --link-check --setup'"
    if not _SCRIPT.is_file():
        return "scripts/link_sandbox_bwrap.py is missing from this installation; reinstall SmoothCast"
    return ""


def install() -> tuple[bool, str]:
    """Create or refresh the wrapper. Returns (ok, plain message)."""
    reason = unsupported_reason()
    if reason:
        return False, reason
    path = wrapper_path()
    body = f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(_SCRIPT))} \"$@\"\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.chmod(0o700)
        os.replace(tmp, path)
    except OSError as exc:
        return False, f"could not write {path}: {exc.strerror or exc}"
    return True, str(path)

