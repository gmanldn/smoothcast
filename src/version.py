"""SmoothCast's single authoritative semantic version.

Owner policy: one PATCH bump per completed GitHub ticket, not every transient
commit. A bumped develop checkout is not a published release until protected
promotion to main succeeds. A running process keeps its imported version until
restart, even if asynchronous updates change the checkout.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

MAJOR = 1
MINOR = 2
PATCH = 34

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
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        name = statement.targets[0].id
        value = statement.value
        if name in {"MAJOR", "MINOR", "PATCH"} and isinstance(value, ast.Constant):
            if type(value.value) is int and value.value >= 0:
                parts[name] = value.value
    if set(parts) != {"MAJOR", "MINOR", "PATCH"}:
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


def read_checkout_revision(repo: Path) -> str | None:
    """Read the checkout's HEAD without Git, network, import or app mutation.

    Supports normal .git directories, detached worktrees and packed refs.
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
        return None

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


if __name__ == "__main__":
    print(f"SmoothCast {label()}")