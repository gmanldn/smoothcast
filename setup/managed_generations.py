"""Offline, fail-closed staging of one candidate source generation (#580).

Only a caller that independently authenticates an exact-channel manifest may use
this primitive. It never selects, installs, activates or deletes a generation.
No network, subprocess, GTK, pip, current/previous mutation or user-data access.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

MAX_FILES = 100_000
MAX_FILE_BYTES = 1 << 30
MAX_TOTAL_BYTES = 4 << 30
BUFFER = 1 << 20
BUILD_MARKER = "src/.smoothcast-build"
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class StageError(ValueError):
    """Candidate is not safe or complete; existing installation is unchanged."""


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise StageError("Refusing a linked release directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise StageError("Release directory is not a private directory")
    if os.name != "nt":
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise StageError("Release directory must be owned and private")


def _safe_name(name: object) -> str:
    if not isinstance(name, str) or not 0 < len(name) <= 512:
        raise StageError("Invalid manifest path")
    if any(c in name for c in ("\\", ":", "\x00")):
        raise StageError("Non-portable manifest path")
    path = PurePosixPath(name)
    if (path.is_absolute() or not path.parts or any(p in ("", ".", "..") for p in name.split("/"))
            or "/".join(path.parts) != name):
        raise StageError("Unsafe manifest path")
    return name


def _manifest(entries: object) -> list[tuple[str, int, str]]:
    if not isinstance(entries, dict) or not 0 < len(entries) <= MAX_FILES:
        raise StageError("Empty or oversized generation manifest")
    planned: list[tuple[str, int, str]] = []
    names: set[str] = set()
    components: dict[str, str] = {}
    total = 0
    for raw_name, attributes in entries.items():
        name = _safe_name(raw_name)
        # Windows and portable macOS filesystems may be case-insensitive.
        folded = name.casefold()
        if folded in names:
            raise StageError("Duplicate or case-colliding manifest paths")
        names.add(folded)
        for i in range(1, len(name.split("/")) + 1):
            prefix = "/".join(name.split("/")[:i])
            prior = components.setdefault(prefix.casefold(), prefix)
            if prior != prefix:
                raise StageError("Directory names collide by case")
        if name == "stage-manifest.json":
            raise StageError("Candidate uses reserved stage manifest path")
        if not isinstance(attributes, dict):
            raise StageError("Invalid file metadata")
        size, digest = attributes.get("size"), attributes.get("sha256")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise StageError("Invalid file size")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise StageError("Invalid SHA-256 digest")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise StageError("Generation exceeds staging byte budget")
        planned.append((name, size, digest))
    return sorted(planned)


def _copy_one(source: Path, dest: Path, size: int, digest: str) -> None:
    # Validate every parent component before opening a source path. O_NOFOLLOW
    # and fstat reject swapped final symlinks, special files and hard links.
    for parent in (source, *source.parents):
        if parent.is_symlink():
            raise StageError("Source contains a symbolic-link component")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
        with os.fdopen(fd, "rb") as reader:
            info = os.fstat(reader.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StageError("Source is not an ordinary private file")
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            calculated = hashlib.sha256()
            read = 0
            with dest.open("xb") as writer:
                while True:
                    block = reader.read(min(BUFFER, size + 1 - read))
                    if not block:
                        break
                    read += len(block)
                    if read > size:
                        raise StageError("Source grew beyond declared size")
                    calculated.update(block)
                    writer.write(block)
                if os.name != "nt":
                    os.fchmod(writer.fileno(), 0o700 if info.st_mode & 0o100 else 0o600)
                writer.flush()
                os.fsync(writer.fileno())
            if read != size or not hmac.compare_digest(calculated.hexdigest(), digest):
                raise StageError("Candidate file changed or failed SHA-256 verification")
    except OSError as exc:
        raise StageError(f"Cannot stage candidate file: {exc.strerror or type(exc).__name__}") from exc


def _sync_dir(path: Path) -> None:
    if os.name == "nt":
        return  # Windows durable directory publication needs native qualification.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_local_snapshot(root: Path, source: Path, commit: str, entries: object) -> Path:
    """Stage a locally supplied candidate; NEVER switch the active generation.

    The manifest/signature trust decision belongs to the future downloader.
    The returned path is a checksum-verified, non-activated release directory.
    """
    # Do not silently weaken race-resistant source handles on Windows.
    # Win32 FILE_FLAG_OPEN_REPARSE_POINT verification is a later #580 gate.
    if not hasattr(os, "O_NOFOLLOW"):
        raise StageError("Secure source staging requires no-follow file handles")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise StageError("Candidate commit must be an immutable lowercase SHA")
    planned = _manifest(entries)  # Reject unsafe names before any source I/O.
    root, source = Path(root), Path(source)
    if root.is_symlink() or source.is_symlink():
        raise StageError("Refusing a linked root/source")
    # Canonicalise benign platform aliases such as macOS /tmp -> /private/tmp.
    root, source = root.resolve(), source.resolve()
    if root == source or root in source.parents:
        raise StageError("Cannot stage from within the installation")
    releases = root / "releases"
    _directory(root)
    _directory(releases)
    target = releases / commit
    if target.exists() or target.is_symlink():
        raise StageError("Generation already exists; never overwrite a verified release")
    if shutil.disk_usage(releases).free < sum(size for _name, size, _sha in planned) * 2:
        raise StageError("Insufficient free space to stage and preserve rollback")
    temporary = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
    published = False
    try:
        for name, size, digest in planned:
            _copy_one(source.joinpath(*name.split("/")),
                      temporary.joinpath(*name.split("/")), size, digest)
        payload = {name: {"size": size, "sha256": digest}
                   for name, size, digest in planned}
        # Record the generation's own identity so a launched copy can prove the
        # exact commit it loaded (src/version.py reads this same marker).
        if BUILD_MARKER in payload:
            raise StageError("Candidate supplies the reserved build marker")
        marker = (commit + "\n").encode("ascii")
        marker_path = temporary / BUILD_MARKER
        marker_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The build marker is part of the verified generation, not just
        # metadata. Flush its bytes before publishing the release directory.
        with os.fdopen(os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(marker)
            output.flush()
            os.fsync(output.fileno())
        payload[BUILD_MARKER] = {"size": len(marker),
                                 "sha256": hashlib.sha256(marker).hexdigest()}
        manifest_file = temporary / "stage-manifest.json"
        if manifest_file.exists():
            raise StageError("Reserved manifest path supplied by candidate")
        with manifest_file.open("x", encoding="utf-8") as output:
            json.dump({"commit": commit, "files": payload}, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        if os.name != "nt":
            manifest_file.chmod(0o600)
        for directory in sorted((p for p in temporary.rglob("*") if p.is_dir()),
                                key=lambda p: len(p.parts), reverse=True):
            _sync_dir(directory)
        _sync_dir(temporary)
        if target.exists() or target.is_symlink():
            raise StageError("Generation appeared during staging")
        temporary.rename(target)
        published = True
        _sync_dir(releases)
        return target
    except BaseException:
        # A failed parent-directory sync must not leave an apparently staged
        # generation whose durable publication is uncertain.
        if published:
            shutil.rmtree(target, ignore_errors=True)
        shutil.rmtree(temporary, ignore_errors=True)
        raise
