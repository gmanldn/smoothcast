"""Launch-time wiring for the managed updater (#581).

``managed_activation`` switches a single atomic reference and waits for the new
primary to confirm its exact commit; this module is the launch-time half of that
contract. The launcher settles any interrupted transaction, runs the *verified*
activated generation instead of the flat install, and acknowledges the switch
once the primary publishes the commit it actually loaded. Nothing here starts a
window, signals a process or modifies a release tree: a broken activation always
falls back to a launch that keeps working.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

import managed_activation as ma
import managed_probe

READY_ENV = "SMOOTHCAST_ACTIVATION_READY"
ACK_TIMEOUT = 60.0
_POLL = 0.2


def settle(root: Path) -> str:
    """Replay an interrupted activation at launch; idempotent, no-op when flat."""
    return ma.recover(Path(root))


def activated(root: Path) -> bool:
    """Cheap check: does this installation carry an activation reference at all?"""
    return (Path(root) / ma.ACTIVE).is_file()


def pending(root: Path) -> tuple[str, str] | None:
    """``(txn, commit)`` of a switched generation still awaiting acknowledgement."""
    journal = ma._load_journal(Path(root))
    if journal is not None and journal.get("state") == "switched":
        return journal["txn"], journal["to"]
    return None


def active_launch(root: Path) -> tuple[Path, Path] | None:
    """``(python, app)`` for the activated generation, or None for the flat install.

    A release is honoured only while it is still hash-verified and passes the
    GUI-free health probe, so a broken or tampered activation falls back instead
    of blocking the launcher.
    """
    root = Path(root)
    commit = ma.read_active(root)["current"]
    if commit is None:
        return None
    try:
        ma.verify_release(root, commit)
    except ma.ActivationError:
        return None
    release = root / "releases" / commit
    if managed_probe.default_probe(release) is not True:
        return None
    python = next((release / part for part in managed_probe.VENV_PYTHONS
                   if (release / part).is_file()), None)
    app = release / managed_probe.APP_ENTRY
    return (python, app) if python is not None and app.is_file() else None


def notice(root: Path, running_commit: str | None) -> str | None:
    """'Staged not yet running' text when the reference is ahead of the process."""
    return ma.staged_notice(Path(root), running_commit)


def read_ready(path: Path) -> str | None:
    """The exact commit the primary published, or None; never follows a link."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(Path(path), flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            raw = handle.read(128)
    except OSError:
        return None
    commit = raw.decode("ascii", "ignore").strip().lower()
    return commit if ma.mg._COMMIT.fullmatch(commit) else None


def await_acknowledgement(root: Path, txn: str, commit: str, ready: Path, *,
                          timeout: float = ACK_TIMEOUT, clock=time.time,
                          sleep=time.sleep) -> bool:
    """Acknowledge *txn* once the primary publishes its exact *commit*.

    Returns False on timeout or when the switch is no longer awaiting this
    transaction; ``recover`` settles the reference on the next launch.
    """
    root = Path(root)
    deadline = clock() + timeout
    while True:
        if read_ready(ready) == commit:
            try:
                ma.acknowledge(root, txn, commit, clock=clock)
            except ma.ActivationError:
                return False
            return True
        if clock() >= deadline:
            return False
        sleep(_POLL)
