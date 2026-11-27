"""Read-only update discovery for the running app; explicit legacy checkout apply.

Never mutate loaded Python code from the GTK worker. The optional discovery
fetch updates Git metadata only and validates a pinned origin branch candidate.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import version

# Only the released line may update itself. A detached HEAD, a developer
# branch or a dirty tree is never pulled: that would rewrite someone's work.
ELIGIBLE_BRANCHES = frozenset({"main", "master"})
UPDATE_CHANNELS = frozenset({"develop", "main"})


def is_installed_build() -> bool:
    """True in a packaged/installed app, never a source checkout.

    An installed (frozen) build is replaced by a new signed installer, never by
    git: a nested ``.git`` or an unusual working directory must not re-enable
    the source updater (#533).
    """
    return bool(getattr(sys, "frozen", False))


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


def _downloaded_notice(repo: Path) -> str | None:
    """Tell the user a new release was downloaded; never claim it is running."""
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


def _signature_ok(repo: Path, sha: str, timeout: int) -> bool:
    """True if *sha*, or a tag pointing at it, passes git's GPG verification.

    The trust decision is the user's own keyring: only signatures from keys
    they have imported can verify. ``_git`` returns None for a non-zero exit.
    """
    if _git(repo, ["verify-commit", sha], timeout) is not None:
        return True
    tags = (_git(repo, ["tag", "--points-at", sha], timeout) or "").splitlines()
    return any(_git(repo, ["verify-tag", tag], timeout) is not None for tag in tags[:20])


def _verified_update(repo: Path, branch: str, before: str, timeout: int) -> str | None:
    """Fetch, authenticate and only then fast-forward; never pull blindly."""
    target = _fetch_branch(repo, branch, timeout)
    if not target:
        return None
    # Tags are verified only for the pinned branch SHA, never FETCH_HEAD.
    _git(repo, ["fetch", "--quiet", "--tags", "origin"], timeout)
    if not target or target == before:
        return None
    if _git(repo, ["merge-base", "--is-ancestor", before, target], timeout) is None:
        return None  # not a fast-forward: leave local history alone
    if not _signature_ok(repo, target, timeout):
        return (
            f"A SmoothCast update ({target[:8]}) is available but was not applied: "
            "its signature could not be verified. Update manually or turn off "
            "'verify_updates' in config.json."
        )
    if _git(repo, ["merge", "--ff-only", target], timeout) is None:
        return None
    after = _git(repo, ["rev-parse", "HEAD"], timeout)
    if after is None or after == before:
        return None
    return _downloaded_notice(repo)


def _semver(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 3 or any(not p.isdecimal() for p in parts):
        return None
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def _fetch_branch(repo: Path, branch: str, timeout: int) -> str | None:
    """Fetch one release branch and return an immutable, explicitly named SHA.

    Never rely on FETCH_HEAD after a tag fetch: that pseudo-ref may have been
    replaced by another fetch. A refspec pins the intended origin branch.
    """
    if branch not in ELIGIBLE_BRANCHES | UPDATE_CHANNELS:
        return None
    ref = f"refs/remotes/origin/{branch}"
    if _git(repo, ["fetch", "--quiet", "--no-tags", "origin",
                   f"+refs/heads/{branch}:{ref}"], timeout) is None:
        return None
    sha = _git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"], timeout)
    if not sha or len(sha) not in (40, 64) or any(c not in "0123456789abcdef" for c in sha):
        return None
    return sha


def find_candidate(repo: Path, timeout: int = 8, *, enabled: bool = False,
                   verify: bool = True, channel: str = "main"
                   ) -> tuple[str, str, bool | None] | None:
    """Read-only check: ``(candidate_sha, release_version, signed)`` or None.

    ``signed`` is None when verification was not requested. The only network
    operation is a bounded fetch of one release branch (and tags only when
    verifying). A failed or malformed probe, or an installed/frozen package,
    yields None rather than a claim of an update.
    """
    if (not enabled or not isinstance(channel, str) or channel not in UPDATE_CHANNELS
            or is_installed_build() or not (repo / ".git").exists()):
        return None
    branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout)
    if branch not in ELIGIBLE_BRANCHES:
        return None
    status = _git(repo, ["status", "--porcelain"], timeout)
    if status is None or status:
        return None
    before = _git(repo, ["rev-parse", "HEAD"], timeout)
    if not before:
        return None
    candidate = _fetch_branch(repo, channel, timeout)
    if not candidate or candidate == before:
        return None
    if _git(repo, ["merge-base", "--is-ancestor", before, candidate], timeout) is None:
        return None
    # Never read arbitrary candidate Python using import/exec; bound the blob
    # before asking git to emit it into memory.
    size = _git(repo, ["cat-file", "-s", f"{candidate}:src/version.py"], timeout)
    if size is None or not size.isdecimal() or int(size) > 65536:
        return None
    source = _git(repo, ["show", f"{candidate}:src/version.py"], timeout)
    release = version.parse_version_text(source) if source is not None else None
    if not release or _semver(release) is None:
        return None
    # Develop may advance through commits without changing its semantic version.
    if (_semver(release) < _semver(version.__version__)
            or (channel == "main" and _semver(release) == _semver(version.__version__))):
        return None
    signed: bool | None = None
    if verify:
        # Tag signatures are checked against the pinned candidate SHA, never a
        # mutable FETCH_HEAD or a tag that targets a different commit.
        _git(repo, ["fetch", "--quiet", "--tags", "origin"], timeout)
        signed = _signature_ok(repo, candidate, timeout)
    return candidate, release, signed


def check_release(repo: Path, timeout: int = 8, *, enabled: bool = False,
                  verify: bool = True, channel: str = "main") -> str | None:
    """Opt-in read-only update notice. Never merges/pulls/restarts the running app."""
    found = find_candidate(repo, timeout, enabled=enabled, verify=verify, channel=channel)
    if found is None:
        return None
    candidate, release, signed = found
    if signed is False:
        return (f"SmoothCast v{release} may be available, but its signature "
                "could not be verified. No files were changed. Use a trusted "
                "installer or review your update-signing keys.")
    return (f"SmoothCast v{release} is available on {channel} ({candidate[:12]}); "
            f"running v{version.__version__}. No files were changed. "
            "Safe staged installation is not yet available.")


def refresh_checkout(repo: Path, timeout: int = 8, *, enabled: bool = False,
                     verify: bool = False) -> str | None:
    """Legacy explicit source-checkout fast-forward; NEVER call from live GTK.

    This mutates on-disk code and is kept only for explicit, offline/controlled
    maintenance. It defaults disabled and the running desktop uses the
    non-mutating ``check_release`` instead.

    Running Python modules remain loaded; new checkout code takes effect on the
    next launch. Extracted release archives do not use git auto-updates, and a
    detached HEAD, a non-release branch or uncommitted work is never touched.
    Whether anything changed is decided by comparing HEAD before and after the
    pull, so a localised or atypically quiet git cannot fake or hide a change.

    ``enabled=False`` (the ``auto_update`` setting) skips everything, including
    any git or network access. ``verify=True`` (``verify_updates``) fetches and
    fast-forwards only to a commit, or a tag on it, whose signature passes
    ``git verify-commit`` / ``git verify-tag``; otherwise it reports instead
    of pulling.
    """
    if not enabled:
        return None
    if is_installed_build():
        return None
    if not (repo / ".git").exists():
        return None
    branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout)
    if branch not in ELIGIBLE_BRANCHES:
        return None
    status = _git(repo, ["status", "--porcelain"], timeout)
    if status is None or status:
        return None
    before = _git(repo, ["rev-parse", "HEAD"], timeout)
    if before is None:
        return None
    if verify:
        return _verified_update(repo, str(branch), before, timeout)
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
    return _downloaded_notice(repo)
