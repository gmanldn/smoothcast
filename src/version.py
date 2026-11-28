"""SmoothCast's single authoritative semantic version.

Owner policy: new versions are made in `develop`; the Git SHA also identifies
each develop revision. Main integration and publication remain owner-manual.
A running process retains its imported version until restart, even if the
checkout changes asynchronously.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re

import commit_identity

MAJOR = 2
MINOR = 3
PATCH = 306

__version__ = f"{MAJOR}.{MINOR}.{PATCH}"


def label() -> str:
    """Canonical human-readable version for CLI and GTK: vMAJOR.MINOR.PATCH."""
    return f"v{__version__}"


def parse_version_text(source: str) -> str | None:
    """Extract a semantic version from untrusted source without executing code."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError, TypeError):
        return None
    parts: dict[str, int] = {}
    names = {"MAJOR", "MINOR", "PATCH"}
    permitted: set[int] = set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        name = statement.targets[0].id
        if name not in names:
            continue
        value = statement.value
        if (name in parts or not isinstance(value, ast.Constant)
                or type(value.value) is not int or not 0 <= value.value <= 2_147_483_647):
            return None
        parts[name] = value.value
        permitted.add(id(statement.targets[0]))
    if set(parts) != names:
        return None
    # A candidate may contain code we must never execute. Refuse ambiguous
    # rebinding rather than reporting a version that differs from runtime.
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and node.id in names
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and id(node) not in permitted):
            return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in names:
                return None
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name.split(".", 1)[0]) in names
                   for alias in node.names):
                return None
    return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"

def read_checkout_version(path: Path) -> str | None:
    """Read on-disk version without importing it or mutating runtime state."""
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        return None
    return parse_version_text(source)


_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_REF = re.compile(r"refs/heads/[A-Za-z0-9._/-]+\Z")


def _read_small(path: Path, size: int = 4096) -> str | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(size + 1)
        return raw.decode("ascii") if len(raw) <= size else None
    except (OSError, UnicodeError):
        return None


def build_label(revision: str | None) -> str:
    """Human-readable source build identity; retain canonical SemVer in metadata.

    A process must supply the revision it captured at launch; do not read a
    moving checkout HEAD and pretend it identifies running loaded code.
    Frozen distributions without embedded source identity report SemVer only.
    """
    if revision and _SHA.fullmatch(revision):
        return f"{label()}+g{revision[:12].lower()}"
    return label()


def _installed_revision(repo: Path) -> str | None:
    marker = repo / "src" / ".smoothcast-build"
    if marker.is_symlink() or not marker.is_file():
        return None
    raw = _read_small(marker, 128)
    lines = raw.splitlines() if raw else []
    sha = lines[0].strip() if lines else ""
    return sha.lower() if _SHA.fullmatch(sha) else None


def read_checkout_revision(repo: Path) -> str | None:
    """Read the checkout's HEAD without Git, network, import or app mutation.

    Supports normal .git directories, detached worktrees, packed refs and
    installer-recorded source provenance for copied applications.
    Fail closed for malformed/missing refs; never infer a running SHA from a
    version number.
    """
    dot_git = Path(repo) / ".git"
    if dot_git.is_file():
        pointer = _read_small(dot_git, 1024)
        if not pointer or not pointer.startswith("gitdir: "):
            return None
        folder = Path(pointer[8:].strip())
        gitdir = (folder if folder.is_absolute()
                  else dot_git.parent / folder).resolve()
    elif dot_git.is_dir():
        gitdir = dot_git
    else:
        return _installed_revision(repo) if not dot_git.exists() else None

    head = _read_small(gitdir / "HEAD", 256)
    if head is None:
        return None
    head = head.strip()
    if _SHA.fullmatch(head):
        return head.lower()
    if not head.startswith("ref: "):
        return None
    ref = head[5:].strip()
    if (not _REF.fullmatch(ref) or "//" in ref
            or any(part in (".", "..") for part in ref.split("/"))):
        return None

    common = gitdir
    common_text = _read_small(gitdir / "commondir", 1024)
    if common_text:
        folder = Path(common_text.strip())
        common = (folder if folder.is_absolute() else gitdir / folder).resolve()
    for base in (gitdir, common):
        loose = _read_small(base / ref, 256)
        if loose and _SHA.fullmatch(loose.strip()):
            return loose.strip().lower()
    packed = _read_small(common / "packed-refs", 2 * 1024 * 1024)
    if packed is not None:
        for line in packed.splitlines():
            if line.startswith("#") or line.startswith("^"):
                continue
            sha, separator, name = line.partition(" ")
            if separator and name == ref and _SHA.fullmatch(sha):
                return sha.lower()
    return None


def registered_checkout(repo: Path) -> Path | None:
    """Locate an installer-recorded checkout for read-only update notices."""
    marker = repo / "src" / ".smoothcast-source"
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        with marker.open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return None
        value = json.loads(raw)
        if not isinstance(value, str) or not Path(value).is_absolute():
            return None
        source = Path(value).resolve()
        root = repo.resolve()
        if (source == root or source in root.parents or root in source.parents
                or not (source / ".git").exists()
                or not (source / "setup" / "bootstrap.py").is_file()
                or 'name = "smoothcast"' not in
                (source / "pyproject.toml").read_text(encoding="utf-8")):
            return None
        return source
    except (OSError, ValueError, RuntimeError):
        return None


def read_checkout_commit_date(repo: Path, revision: str | None = None) -> str | None:
    """Read a commit's committer date without Git, network or app mutation."""
    return commit_identity.read_checkout_commit_date(
        repo, read_checkout_revision(repo) if revision is None else revision)


# Freeze the identity when this module is loaded. A later installer copy
# must never relabel an already-running process.
RUNNING_REVISION = read_checkout_revision(Path(__file__).resolve().parents[1])
RUNNING_COMMIT_DATE = read_checkout_commit_date(
    Path(__file__).resolve().parents[1], RUNNING_REVISION)


def running_label() -> str:
    """Display the source build loaded by this process, not the moving disk."""
    return build_label(RUNNING_REVISION)


def identity_label() -> str:
    """Prominent running-build identity: version, commit date and codename."""
    return commit_identity.display_label(label(), RUNNING_REVISION, RUNNING_COMMIT_DATE)


if __name__ == "__main__":
    print(f"SmoothCast {label()}")