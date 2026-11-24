"""SmoothCast's single authoritative semantic version.

Owner policy: normal agent ships identify each develop revision by Git SHA
without changing SemVer. Only explicit owner-authorised release operations
assign release numbers; main integration and publication remain owner-manual.
A running process retains its imported version until restart, even if the
checkout changes asynchronously.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

MAJOR = 2
MINOR = 0
PATCH = 15

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
    sha = raw.strip() if raw else ""
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


# Freeze the identity when this module is loaded. A later installer copy
# must never relabel an already-running process.
RUNNING_REVISION = read_checkout_revision(Path(__file__).resolve().parents[1])


def running_label() -> str:
    """Display the source build loaded by this process, not the moving disk."""
    return build_label(RUNNING_REVISION)


if __name__ == "__main__":
    print(f"SmoothCast {label()}")