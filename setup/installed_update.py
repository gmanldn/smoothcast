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
LATEST_TIP_ENV = "SMOOTHCAST_LATEST_DEVELOP_TIP"


def _source_at_tip(source: Path, installed: Path, tip: str) -> Path | None:
    """Only use a clean official develop checkout when it matches the pinned tip."""
    try:
        if not source.is_absolute():
            return None
        source = source.resolve(strict=True)
        destination = installed.resolve()
        if (source == destination or source in destination.parents or destination in source.parents
                or not (source / ".git").exists()
                or not (source / "setup" / "bootstrap.py").is_file()
                or 'name = "smoothcast"' not in
                (source / "pyproject.toml").read_text(encoding="utf-8")):
            return None
        head = _git(source, "rev-parse", "--verify", "HEAD", timeout=5)
        branch = _git(source, "symbolic-ref", "--short", "HEAD", timeout=5)
        origin = _git(source, "remote", "get-url", "origin", timeout=5).rstrip("/")
        clean = checkout_refresh.install_location._clean_source_revision(source)
    except (OSError, subprocess.SubprocessError):
        return None
    official = {
        ORIGIN.removesuffix(".git"),
        "git@github.com:gmanldn/smoothcast",
        "ssh://git@github.com/gmanldn/smoothcast",
    }
    if (head != tip or clean != tip or branch != "develop"
            or origin.removesuffix(".git") not in official):
        return None
    return source


def _local_source_at_tip(installed: Path, tip: str) -> Path | None:
    """Resolve the invoking checkout or install-recorded checkout, independent of cwd."""
    requested = os.environ.pop("SMOOTHCAST_LAUNCH_SOURCE", None)
    candidates = []
    if isinstance(requested, str) and requested:
        candidates.append(Path(requested))
    registered = checkout_refresh.installed_source(installed)
    if registered is not None:
        candidates.append(registered)
    for source in candidates:
        accepted = _source_at_tip(source, installed, tip)
        if accepted is not None:
            return accepted
    return None


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
                os.environ[LATEST_TIP_ENV] = tip
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
                    # Agent commits can be unsigned. Preserve signature policy for
                    # downloaded candidates; an explicitly registered, clean local
                    # develop checkout may supply the exact pinned tip instead.
                    local_source = _local_source_at_tip(installed, tip)
                    if local_source is None:
                        raise managed_source.SourceError("develop build has no trusted signature") from None
                    print("SmoothCast: using the clean local develop checkout for the "
                          f"pinned build {tip[:12]}.", file=sys.stderr, flush=True)
                    code = checkout_refresh.refresh(
                        local_source, installed, target, running, verified_tip=tip)
                    if code == 0 and checkout_refresh.installed_revision(installed) == tip:
                        os.environ[LATEST_TIP_ENV] = tip
                    return code
            _git(source, "-c", "core.hooksPath=/dev/null", "reset", "--hard", tip)
            code = checkout_refresh.refresh(source, installed, target, running,
                                            verified_tip=tip)
            if code == 0 and checkout_refresh.installed_revision(installed) == tip:
                os.environ[LATEST_TIP_ENV] = tip
            return code
    except (OSError, subprocess.SubprocessError, managed_source.SourceError) as exc:
        reason = str(exc) if isinstance(exc, managed_source.SourceError) else type(exc).__name__
        print(f"SmoothCast: develop update unavailable ({reason}); loading installed build.",
              file=sys.stderr, flush=True)
        return 0
