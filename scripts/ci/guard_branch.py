"""Refuse commits made while ``main`` is checked out (local pre-commit guard).

Agents integrate on ``develop``; ``main`` only receives releases through the
automated develop -> main pull request. A detached HEAD (the recommended
per-task worktree) and every other branch are allowed.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

PROTECTED = frozenset({"main", "master"})


def current_branch(repo: Path | None = None) -> str | None:
    """Checked-out branch name, or None for a detached HEAD / non-repo."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        cwd=repo, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() or None if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    branch = current_branch(Path(argv[0]) if argv else None)
    if branch in PROTECTED:
        print(
            f"Refusing to commit on '{branch}': it is release-only. Integrate on "
            "'develop' (see docs/agents/workflow.md): "
            "git worktree add --detach ../smoothcast-N origin/develop",
            file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
