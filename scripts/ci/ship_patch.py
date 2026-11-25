"""Retry-safe, private-worktree PATCH allocation for agent ship.

The version commit is *unpublished* until git push succeeds. If another agent
wins the remote race, discard ONLY the exact generated version-only commit,
rebase the user's own code, and allocate the next patch at the new remote tip.
No force, reset --hard, rewrite of published history or main operations.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

VERSION_PATH = "src/version.py"
MARKER = "[sc-auto-patch]"
PART = re.compile(r"^(MAJOR|MINOR|PATCH)(\s*=\s*)(\d+)(\s*)$", re.MULTILINE)


class PatchAllocationError(RuntimeError):
    pass


def run(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if proc.returncode:
        raise PatchAllocationError(
            f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip()[:240]}")
    return proc.stdout.strip()


def parsed(source: str) -> tuple[int, int, int]:
    found = list(PART.finditer(source))
    if len(found) != 3 or set(m.group(1) for m in found) != {"MAJOR", "MINOR", "PATCH"}:
        raise PatchAllocationError("version.py has ambiguous semantic version assignments")
    value = {m.group(1): int(m.group(3)) for m in found}
    return value["MAJOR"], value["MINOR"], value["PATCH"]


def patch_source(source: str) -> str:
    major, minor, patch = parsed(source)
    if patch >= 2_147_483_647:
        raise PatchAllocationError("PATCH overflow; owner must choose next MINOR")
    return PART.sub(
        lambda m: m.group(1) + m.group(2) +
        (str(patch + 1) if m.group(1) == "PATCH" else m.group(3)) + m.group(4),
        source,
    )


def is_generated_head(root: Path) -> bool:
    return run(root, "log", "-1", "--format=%s").endswith(MARKER)


def recover_private_patch(root: Path, remote_sha: str) -> bool:
    """Drop our *unpublished* version-only commit after a contested push.

    This is deliberately limited to the exact generated marker and one file.
    A lost push acknowledgement that did land on remote is never undone.
    """
    if not is_generated_head(root):
        return False
    sha = run(root, "rev-parse", "HEAD")
    probe = subprocess.run(["git", "merge-base", "--is-ancestor", sha, remote_sha],
                           cwd=root, capture_output=True)
    if probe.returncode == 0:
        return False
    if probe.returncode != 1:
        raise PatchAllocationError("cannot determine remote ancestry; preserving work")
    if run(root, "status", "--porcelain"):
        raise PatchAllocationError("worktree dirty; refusing to discard a generated commit")
    if run(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") != VERSION_PATH:
        raise PatchAllocationError("generated commit changed non-version files")
    before = run(root, "show", "HEAD^:" + VERSION_PATH)
    after = run(root, "show", "HEAD:" + VERSION_PATH)
    expected = patch_source(before)
    if after != expected:
        raise PatchAllocationError("generated commit is not an exact one-step patch")
    # Only the tool-generated, unpublished VERSION-only commit is removed.
    run(root, "reset", "--soft", "HEAD^")
    run(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", VERSION_PATH)
    return True


def published_assignment(root: Path, remote_sha: str, issue: int) -> str | None:
    """Return the earliest verified assignment reachable from the fetched tip.

    The exact subject is the durable issue key. Ignore substring/body matches;
    reject forged or malformed assignments instead of guessing. Existing
    historical duplicates are retained, never repaired by rewriting history.
    """
    if type(issue) is not int or issue < 1:
        raise PatchAllocationError("positive GitHub issue number required")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", remote_sha):
        raise PatchAllocationError("full fetched remote SHA required")
    suffix = f" for issue #{issue} {MARKER}"
    subject = re.compile(r"chore\(version\): PATCH(?: (\d+\.\d+\.\d+))?"
                         + re.escape(suffix))
    # Shallow history cannot establish that an issue was never assigned.
    if run(root, "rev-parse", "--is-shallow-repository") != "false":
        raise PatchAllocationError("complete remote history required; fetch --unshallow")
    matches = run(root, "log", "--reverse", "--topo-order", "--format=%H%x09%s",
                  "--fixed-strings", f"--grep={suffix}", remote_sha, "--")
    for line in matches.splitlines():
        sha, sep, title = line.partition("\t")
        match = subject.fullmatch(title) if sep else None
        if match is None:
            # Unrelated commit bodies are not assignments. A malformed subject
            # claiming this issue must not permit a second version allocation.
            if title.startswith("chore(version): PATCH") and title.endswith(suffix):
                raise PatchAllocationError("malformed published assignment subject")
            continue
        parents = run(root, "rev-list", "--parents", "-n", "1", sha).split()
        if len(parents) != 2:
            raise PatchAllocationError("published assignment is not a single-parent commit")
        if run(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha) != VERSION_PATH:
            raise PatchAllocationError("published assignment changed non-version files")
        before = run(root, "show", parents[1] + ":" + VERSION_PATH)
        after = run(root, "show", sha + ":" + VERSION_PATH)
        if after != patch_source(before):
            raise PatchAllocationError("published assignment is not an exact one-step patch")
        if match[1] is not None and match[1] != ".".join(map(str, parsed(after))):
            raise PatchAllocationError("published assignment subject/version mismatch")
        return sha
    return None


def assign_private_patch(root: Path, remote_sha: str, issue: int) -> str | None:
    """Append exactly one version-only commit to this pending shipment.

    Caller fetched remote and rebased all pending code before invoking. If a
    developer already made a valid SemVer bump, do not mint a second number.
    The final non-force push is the atomic CAS/fencing operation on develop.
    """
    if type(issue) is not int or issue < 1:
        raise PatchAllocationError("positive GitHub issue number required")
    if run(root, "status", "--porcelain"):
        raise PatchAllocationError("dirty worktree; cannot safely allocate a patch")
    remote = parsed(run(root, "show", remote_sha + ":" + VERSION_PATH))
    local_source = (root / VERSION_PATH).read_text(encoding="utf-8")
    local = parsed(local_source)
    existing = published_assignment(root, remote_sha, issue)
    if existing:
        if local != remote:
            raise PatchAllocationError(
                f"issue #{issue} already assigned at {existing[:12]}; "
                "preserve code and remove the unpublished extra version change")
        return None
    if is_generated_head(root):
        raise PatchAllocationError("generated patch already present; recover before rebasing")
    if local != remote:
        if (local == (remote[0], remote[1], remote[2] + 1)
                or local == (remote[0], remote[1] + 1, 0)
                or local == (remote[0] + 1, 0, 0)):
            return None  # Existing explicit bump; do not double-assign.
        raise PatchAllocationError(f"version mismatch: remote {remote}, local {local}")
    (root / VERSION_PATH).write_text(patch_source(local_source), encoding="utf-8")
    try:
        run(root, "add", "--", VERSION_PATH)
        run(root, "commit", "-m", f"chore(version): PATCH for issue #{issue} {MARKER}")
    except BaseException:
        # Leave all code commits intact and restore only our generated file.
        run(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", VERSION_PATH)
        raise
    return run(root, "rev-parse", "HEAD")
