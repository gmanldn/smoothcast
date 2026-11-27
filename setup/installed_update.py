"""Check official develop for a registered, idle Linux source installation."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import checkout_refresh
import managed_source
import managed_startup

ORIGIN = "https://github.com/gmanldn/smoothcast.git"
BRANCH = "refs/heads/develop"
COMMIT = re.compile(r"[0-9a-f]{40}")


def _git(repo: Path, *args: str, timeout: int = 30) -> str:
    # Do not inherit a caller's Git repository, index, or object store.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(["git", "-C", str(repo), *args], env=env,
                            capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout.strip()


def refresh(installed: Path, target: str, running) -> int:
    """Use the existing source installer after a signed forward update is pinned."""
    if (target != "linux" or not Path("/proc/self/cmdline").is_file()
            or managed_startup.activated(installed) or running()):
        return 0
    previous = checkout_refresh.installed_revision(installed)
    try:
        with tempfile.TemporaryDirectory(prefix="smoothcast-develop-") as scratch:
            directory = Path(scratch)
            tip, sep, ref = _git(directory, "ls-remote", "--exit-code", ORIGIN, BRANCH,
                                 timeout=5).partition("\t")
            if not sep or ref != BRANCH or not COMMIT.fullmatch(tip):
                raise managed_source.SourceError("develop did not resolve to a commit")
            if tip == previous:
                return 0

            print("SmoothCast: checking the newer develop build…", file=sys.stderr, flush=True)
            source = directory / "source"
            _git(directory, "clone", "--quiet", "--filter=blob:none", "--single-branch",
                 "--branch", "develop", "--no-checkout", ORIGIN, str(source))
            if _git(source, "rev-parse", "HEAD") != tip:
                raise managed_source.SourceError("develop advanced during download; retry on next launch")
            # Use the same trusted signature mechanism as managed acquisition.
            # Resolve only local tags from this official clone.
            try:
                _git(source, "verify-commit", tip, timeout=5)
            except subprocess.CalledProcessError:
                for tag in _git(source, "tag", "--points-at", tip).splitlines()[:managed_source.MAX_TAGS]:
                    try:
                        _git(source, "verify-tag", "--", tag, timeout=5)
                        break
                    except subprocess.CalledProcessError:
                        continue
                else:
                    raise managed_source.SourceError("develop build has no trusted signature") from None
            _git(source, "-c", "core.hooksPath=/dev/null", "reset", "--hard", tip)
            return checkout_refresh.refresh(source, installed, target, running)
    except (OSError, subprocess.SubprocessError, managed_source.SourceError) as exc:
        reason = str(exc) if isinstance(exc, managed_source.SourceError) else type(exc).__name__
        print(f"SmoothCast: develop update unavailable ({reason}); loading installed build.",
              file=sys.stderr, flush=True)
        return 0
