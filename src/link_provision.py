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


def setup_and_qualify() -> tuple[bool, str]:
    """Install the wrapper, then attack-test it. Blocking: call off the GTK thread.

    Never enables a provider. ``ok`` means the launcher passed qualification; the
    message says plainly what failed otherwise.
    """
    ok, message = install()
    if not ok:
        return False, message.capitalize() + "."
    import link_sandbox_probe
    launcher = default_launcher()
    if not launcher:
        return False, "The launcher was written but is not usable."
    result = link_sandbox_probe.qualify(launcher)
    link_sandbox_probe.save(launcher, result)
    if result.verified:
        return True, "Isolation passed the attack test. YouTube links can now be enabled; BitTorrent still needs your own launcher."
    return False, "Isolation failed the attack test and stays off" + (": " + result.detail if result.detail else ".")


def start_setup(on_done) -> None:
    """Run ``setup_and_qualify`` on a daemon thread; ``on_done(ok, text)`` runs on that thread."""
    import threading

    def work() -> None:
        try:
            ok, text = setup_and_qualify()
        except Exception as exc:
            ok, text = False, f"Setup failed: {type(exc).__name__}."
        on_done(ok, text)

    threading.Thread(target=work, name="link-setup", daemon=True).start()
