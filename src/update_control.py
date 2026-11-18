"""Best-effort asynchronous checkout refresh; the running UI never blocks."""
from __future__ import annotations

from pathlib import Path
import subprocess

import version

# Only the released line may update itself. A detached HEAD, a developer
# branch or a dirty tree is never pulled: that would rewrite someone's work.
ELIGIBLE_BRANCHES = frozenset({"main", "master"})


def _git(repo: Path, args: list[str], timeout: int) -> str | None:
    """Run one bounded read-only git command; return stripped stdout or None."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def refresh_checkout(repo: Path, timeout: int = 8) -> str | None:
    """Pull a clean git checkout from a worker after the first window is visible.

    Running Python modules remain loaded; new checkout code takes effect on the
    next launch. Extracted release archives do not use git auto-updates, and a
    detached HEAD, a non-release branch or uncommitted work is never touched.
    Whether anything changed is decided by comparing HEAD before and after the
    pull, so a localised or atypically quiet git cannot fake or hide a change.
    """
    if not (repo / ".git").exists():
        return None
    if _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout) not in ELIGIBLE_BRANCHES:
        return None
    status = _git(repo, ["status", "--porcelain"], timeout)
    if status is None or status:
        return None
    before = _git(repo, ["rev-parse", "HEAD"], timeout)
    if before is None:
        return None
    try:
        pulled = subprocess.run(
            ["git", "pull", "--ff-only"], cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if pulled.returncode != 0:
        return None
    after = _git(repo, ["rev-parse", "HEAD"], timeout)
    if after is None or after == before:
        return None
    # A pull changes files on disk; never claim a new release is *running*
    # until the process actually restarts and imports that checkout.
    downloaded = version.read_checkout_version(repo / "src" / "version.py")
    running = version.__version__
    if downloaded and downloaded != running:
        return (
            f"SmoothCast v{downloaded} downloaded; running v{running}. "
            "Restart after playback to apply."
        )
    # Git commits can change without any semantic release. Those edits must
    # not repeatedly prompt the user to restart "the same version" every
    # launch. The downloaded code still takes effect on a normal relaunch.
    return None
