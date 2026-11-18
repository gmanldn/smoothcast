"""Best-effort asynchronous checkout refresh; the running UI never blocks."""
from __future__ import annotations

from pathlib import Path
import subprocess


def refresh_checkout(repo: Path, timeout: int = 8) -> str | None:
    """Pull a git checkout from a worker after the initial window is visible.

    Running Python modules remain loaded; new checkout code takes effect on
    the next launch. Extracted release archives do not use git auto-updates.
    """
    if not (repo / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"], cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output or "Already up to date." in output or "Already up-to-date." in output:
        return None
    return "SmoothCast update downloaded; restart after playback to apply."
