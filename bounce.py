#!/usr/bin/env python3
"""Bring this checkout to the latest develop build without interrupting playback (#626).

An explicit, operator-triggered update. It never runs on ordinary launch, never
touches ``main``, never overwrites a dirty or diverged checkout and never stops
a running SmoothCast: a live primary keeps its code and its media, and the new
build is simply ready for the next start. With no primary running it starts the
canonical launcher (``sc.py``). Preserving a live stream across a restart is a
separate, qualified step that this tool does not fake.

    python3 bounce.py [--dry-run] [--local] [--restart]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CHANNEL = "develop"
FETCH_TIMEOUT = 30.0


def _git(*args: str, timeout: float = 15.0) -> subprocess.CompletedProcess | None:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", LC_ALL="C")
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                              timeout=timeout, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _out(*args: str) -> str | None:
    done = _git(*args)
    return done.stdout.strip() if done is not None and done.returncode == 0 else None


def decide(*, head: str | None, target: str | None, dirty: bool | None,
           ancestor: bool | None, running: bool, restart: bool = False) -> tuple[str, str]:
    """Pure plan: (action, one-line message). Unknown facts fail closed."""
    if head is None or target is None:
        return "refuse", "Cannot read the checkout or the latest build; nothing changed."
    if dirty is not False:
        return "refuse", "This checkout has local changes; commit or stash them first. Nothing changed."
    if head != target:
        if ancestor is not True:
            return "refuse", "This checkout has diverged from the latest build; not overwriting it."
        return ("defer" if running else "update"), (
            f"Update ready ({target[:12]}); waiting for the running SmoothCast or playback to finish. "
            "Playback is untouched." if running else f"Updating to {target[:12]}.")
    if running:
        return ("defer" if restart else "noop"), (
            "Already on the latest build; restart it when playback ends."
            if restart else f"Already running the latest build ({head[:12]}).")
    return "start", f"Already on the latest build ({head[:12]}); starting SmoothCast."


def _launch() -> None:
    subprocess.Popen([sys.executable, str(ROOT / "sc.py")], cwd=str(ROOT), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _running() -> bool:
    # A saved session can outlive its GUI process (for example during a crash
    # or a delayed shutdown callback). Its receiver/worker ownership may still
    # be live, so never treat an unaccounted session as permission to update.
    # The normal stop path removes this file; stale or unreadable state is a
    # safe defer, not a reason to kill a stream whose owner is uncertain.
    try:
        session = Path.home() / ".cache" / "cast-control" / "session.json"
        if session.exists():
            return True
    except (OSError, RuntimeError):
        return True
    sys.path.insert(0, str(ROOT / "setup"))
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import launch
        return bool(launch.gui_instances())
    except Exception:  # an unreadable process table must not look like "idle"
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report the plan; change nothing")
    parser.add_argument("--local", action="store_true", help="use this checkout's HEAD; do not fetch")
    parser.add_argument("--restart", action="store_true", help="restart even when already current")
    args = parser.parse_args(argv)

    print("Checking latest build…")
    if not args.local:
        fetched = _git("fetch", "--quiet", "origin", CHANNEL, timeout=FETCH_TIMEOUT)
        if fetched is None or fetched.returncode != 0:
            print("Could not reach the update source; your current SmoothCast is untouched.")
            return 1
    head = _out("rev-parse", "HEAD")
    target = head if args.local else _out("rev-parse", f"origin/{CHANNEL}")
    status = _git("status", "--porcelain", "--untracked-files=no")
    dirty = None if status is None or status.returncode != 0 else bool(status.stdout.strip())
    ancestor = None
    if head and target:
        probe = _git("merge-base", "--is-ancestor", head, target)
        ancestor = None if probe is None or probe.returncode not in (0, 1) else probe.returncode == 0
    action, message = decide(head=head, target=target, dirty=dirty, ancestor=ancestor,
                             running=_running(), restart=args.restart)
    print(message)
    if args.dry_run or action in ("refuse", "defer", "noop"):
        return 1 if action == "refuse" else 0
    if action == "update":
        merged = _git("merge", "--ff-only", "--quiet", target or "", timeout=60.0)
        if merged is None or merged.returncode != 0:
            print("Could not apply the update cleanly; nothing was changed.")
            return 1
        print(f"Prepared {(target or '')[:12]}.")
    print("Restarting controls…")
    _launch()
    print("SmoothCast is starting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
