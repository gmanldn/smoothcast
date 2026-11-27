"""One-click update: fetch, fast-forward, then restart (#711). GTK-free.

``UpdateRunner`` owns a small state machine shared by the GTK front page and the
web room. It never rewrites history: it fast-forwards a clean checkout that is on
the configured channel branch, optionally only to a signature-verified commit,
and refuses while playback is mid-handoff unless the caller confirms.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

CHANNELS = ("develop", "main")
STATES = ("idle", "checking", "current", "available", "updating", "restarting", "failed")


def _git(repo: Path, args: list[str], timeout: int = 30) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def spawn_relaunch(root: Path, delay: float = 3.0) -> bool:
    """Start a detached launcher that waits for this process to exit, then runs ``sc.py``."""
    script = Path(root) / "sc.py"
    if not script.is_file():
        return False
    try:
        subprocess.Popen(
            ["sh", "-c", f'sleep {float(delay):g}; exec "$0" "$1"', sys.executable, str(script)],
            cwd=root, start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


class UpdateRunner:
    def __init__(self, repo, *, channel: str = "develop", verify: bool = False,
                 busy=lambda: False, quit_app=lambda: None, relaunch=None, git=_git) -> None:
        self.repo = Path(repo)
        self.channel = channel if channel in CHANNELS else "develop"
        self.verify = verify
        self._busy, self._quit, self._git = busy, quit_app, git
        self._relaunch = relaunch or (lambda: spawn_relaunch(self.repo))
        self._lock = threading.Lock()
        self.state, self.message, self.behind = "idle", "Not checked yet.", 0

    def snapshot(self) -> dict:
        with self._lock:
            return self.snapshot_unlocked()

    def _set(self, state: str, message: str, behind: int | None = None) -> None:
        with self._lock:
            self.state, self.message = state, message
            if behind is not None:
                self.behind = behind

    def _eligible(self) -> str | None:
        """None when the checkout may be updated, else a plain-words reason."""
        g = lambda *a: self._git(self.repo, list(a))  # noqa: E731
        if g("rev-parse", "--is-inside-work-tree") != "true":
            return "This install is not a source checkout, so it updates through its installer."
        if g("rev-parse", "--abbrev-ref", "HEAD") != self.channel:
            return f"This checkout is not on the {self.channel} branch."
        if g("status", "--porcelain") != "":
            return "This checkout has local changes, so it was left alone."
        return None

    def check(self) -> dict:
        with self._lock:
            if self.state in ("updating", "restarting"):
                return self.snapshot_unlocked()
            if self.state == "checking":
                return self.snapshot_unlocked()
        self._set("checking", "Checking for updates…")
        why = self._eligible()
        if why:
            self._set("current", why, 0)
            return self.snapshot()
        if self._git(self.repo, ["fetch", "--quiet", "origin", self.channel], ) is None:
            self._set("failed", "Could not reach the update server. Check your network.")
            return self.snapshot()
        count = self._git(self.repo, ["rev-list", "--count", f"HEAD..origin/{self.channel}"])
        behind = int(count) if count and count.isdigit() else 0
        if behind:
            self._set("available", f"{behind} newer change{'' if behind == 1 else 's'} ready to install.", behind)
        else:
            self._set("current", "SmoothCast is up to date.", 0)
        return self.snapshot()

    def snapshot_unlocked(self) -> dict:
        return {"state": self.state, "message": self.message, "behind": self.behind,
                "channel": self.channel, "can_update": self.state == "available"}

    def apply(self, *, confirmed: bool = False) -> dict:
        with self._lock:
            if self.state != "available":
                return {"ok": False, "message": "No update is ready. Check for updates first."}
            if self._busy() and not confirmed:
                return {"ok": False, "needs_confirmation": True,
                        "message": "Something is playing. Updating restarts SmoothCast and interrupts it."}
            self.state, self.message = "updating", "Installing the update…"
        if self.verify:
            import update_control
            head = self._git(self.repo, ["rev-parse", f"origin/{self.channel}"])
            if not head or not update_control._signature_ok(self.repo, head, 15):
                self._set("failed", "The update is not signed by a trusted key, so it was not installed.")
                return {"ok": False, "message": self.message}
        if self._git(self.repo, ["merge", "--ff-only", f"origin/{self.channel}"], 60) is None:
            self._set("failed", "The update could not be applied cleanly. Nothing was changed.")
            return {"ok": False, "message": self.message}
        self._set("restarting", "Updated. Restarting SmoothCast…", 0)
        if not self._relaunch():
            self._set("failed", "Updated, but SmoothCast could not restart itself. Please reopen it.")
            return {"ok": False, "message": self.message}
        self._quit()
        return {"ok": True, "message": self.message}
