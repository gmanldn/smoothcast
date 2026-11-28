"""Trusted acquisition of one candidate source generation (#580).

Pins the exact selected ``refs/heads/<channel>`` commit, requires signed
provenance through the user's own Git keyring (``git verify-commit`` or a signed
tag on the commit), materialises that commit through the validated archive gate
and returns the complete SHA-256 manifest that
``managed_generations.stage_local_snapshot`` consumes.

It never switches ``current``/``previous``, never runs pip/GTK and leaves the
installation unchanged on any failure. The only network operation is one bounded
fetch of the selected branch (and tags when provenance is verified).
"""
from __future__ import annotations

import re
import subprocess
import shutil
import tempfile
from pathlib import Path

import managed_archive

CHANNELS = ("develop", "main")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
GIT_TIMEOUT = 30
MAX_TAGS = 20


class SourceError(ValueError):
    """Candidate cannot be trusted or acquired; nothing was staged."""


def _git(repo: Path, args: list[str], timeout: int) -> str | None:
    """Return stdout for a successful git command, else None (never raises)."""
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def pin_channel_commit(repo: Path, channel: str, timeout: int = GIT_TIMEOUT) -> str:
    """Fetch exactly ``refs/heads/<channel>`` and return its immutable commit SHA.

    A refspec pins the intended origin branch; ``FETCH_HEAD`` and tags are never
    trusted as the selected ref.
    """
    if channel not in CHANNELS:
        raise SourceError("Unknown update channel")
    ref = f"refs/remotes/origin/{channel}"
    if _git(repo, ["fetch", "--quiet", "--no-tags", "origin",
                   f"+refs/heads/{channel}:{ref}"], timeout) is None:
        raise SourceError("Could not fetch the selected channel")
    sha = _git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"], timeout)
    if not sha or not _SHA.fullmatch(sha):
        raise SourceError("Selected channel did not resolve to an immutable commit")
    return sha


def signed_provenance(repo: Path, commit: str, timeout: int = GIT_TIMEOUT) -> bool:
    """True only when the commit, or a signed tag on it, passes the user's keyring."""
    if not _SHA.fullmatch(commit or ""):
        return False
    if _git(repo, ["verify-commit", commit], timeout) is not None:
        return True
    _git(repo, ["fetch", "--quiet", "--tags", "origin"], timeout)
    tags = (_git(repo, ["tag", "--points-at", commit], timeout) or "").splitlines()
    return any(_git(repo, ["verify-tag", tag], timeout) is not None for tag in tags[:MAX_TAGS])


def export_manifest(repo: Path, commit: str, scratch: Path,
                    timeout: int = GIT_TIMEOUT) -> dict[str, dict]:
    """Export *commit* into a new private *scratch* tree and return its manifest.

    The archive gate validates every entry; a rejected entry or a failed export
    leaves no tree behind and stages nothing.
    """
    archive = Path(scratch) / "candidate.tar"
    try:
        with archive.open("wb") as sink:
            result = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit],
                                    stdout=sink, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceError(f"Could not export the candidate: {exc}") from exc
    if result.returncode or not archive.stat().st_size:
        raise SourceError("Candidate archive export failed")
    return managed_archive.unpack_archive(archive, Path(scratch) / "tree")


def candidate_manifest(repo: Path, commit: str, *, timeout: int = GIT_TIMEOUT,
                       verify=signed_provenance) -> dict[str, dict]:
    """Verify signed provenance and return the complete SHA-256 manifest."""
    if not _SHA.fullmatch(commit or ""):
        raise SourceError("Candidate commit must be an immutable lowercase SHA")
    if not verify(repo, commit, timeout):
        raise SourceError("Candidate signature could not be verified against a trusted key")
    with tempfile.TemporaryDirectory(prefix="smoothcast-candidate-") as scratch:
        return export_manifest(repo, commit, Path(scratch), timeout)


def commit_display_date(repo: Path, commit: str, timeout: int = GIT_TIMEOUT) -> str | None:
    """The commit's committer date and time as "YYYY-MM-DD HHMM" in its own timezone, else None."""
    value = _git(repo, ["show", "-s", "--format=%cI", commit], timeout)
    found = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):\d{2}(?:Z|[+-]\d{2}:\d{2})", value or "")
    return f"{found[1]} {found[2]}{found[3]}" if found else None


def require_free_space(root: Path, entries: object, generations: int = 2) -> None:
    """Refuse to stage unless ``generations`` copies of the candidate fit (#580)."""
    need = 0
    if isinstance(entries, dict):
        for attributes in entries.values():
            size = attributes.get("size") if isinstance(attributes, dict) else None
            if isinstance(size, int) and size > 0:
                need += size
    probe = Path(root)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if shutil.disk_usage(probe).free < need * generations:
        raise SourceError("Not enough free space to stage the update safely")


def stage_trusted_candidate(root: Path, repo: Path, *, channel: str,
                            timeout: int = GIT_TIMEOUT, verify=signed_provenance) -> Path:
    """Pin, verify, export and stage one trusted candidate; never activate it.

    Returns the checksum-verified ``releases/<commit>`` directory. Any failure
    raises :class:`SourceError` (or ``StageError``) leaving the installation,
    ``current``, ``previous`` and user data untouched.
    """
    import managed_generations

    commit = pin_channel_commit(repo, channel, timeout)
    if not verify(repo, commit, timeout):
        raise SourceError("Candidate signature could not be verified against a trusted key")
    with tempfile.TemporaryDirectory(prefix="smoothcast-candidate-") as scratch:
        entries = export_manifest(repo, commit, Path(scratch), timeout)
        require_free_space(root, entries)
        return managed_generations.stage_local_snapshot(
            root, Path(scratch) / "tree", commit, entries,
            commit_date=commit_display_date(repo, commit, timeout))
