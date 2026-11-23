"""Bounded, fail-closed unpacking of an untrusted source archive (#580).

Turns a ``.tar``/``.tar.gz``/``.zip`` candidate into a private scratch tree and
the ``{path: {size, sha256}}`` manifest that ``managed_generations`` stages.
The archive is DATA: nothing is executed, no member is ever extracted through
``tarfile.extract``/``extractall`` and only ordinary files are written.
Authenticating the archive (signature, exact ref SHA) is the caller's job and
must happen first. No network, subprocess, GTK, pip or access to ``current``.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import tarfile
import unicodedata
import zipfile

import managed_generations as mg

MAX_RATIO = 1000  # decompressed:compressed; real source trees are far below
RATIO_FLOOR = 1 << 20  # ratio only matters once a member is this large
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


class _Plan:
    """Running budget and portable-collision ledger for one archive."""

    def __init__(self, strip_prefix: str | None) -> None:
        self.strip = strip_prefix.strip("/") + "/" if strip_prefix else ""
        self.headers = self.files = self.total = 0
        self.folded: dict[str, bool] = {}  # folded path -> is_file
        self.spelling: dict[str, str] = {}  # folded path -> first exact spelling

    def count(self) -> None:
        self.headers += 1
        if self.headers > mg.MAX_FILES * 2:
            raise mg.StageError("Archive has too many entries")

    def name(self, raw: str) -> str | None:
        """Validated manifest path for a member, or None for the stripped root."""
        raw = raw.rstrip("/") if raw.endswith("/") else raw
        if self.strip:
            if raw + "/" == self.strip:
                return None
            if not raw.startswith(self.strip):
                raise mg.StageError("Archive entry outside the expected top directory")
            raw = raw[len(self.strip):]
        name = mg._safe_name(raw)
        if name == "stage-manifest.json":
            raise mg.StageError("Archive uses the reserved stage manifest path")
        for part in name.split("/"):
            base = part.split(".")[0].upper()
            if (part != part.rstrip(". ") or base in _RESERVED
                    or any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn")
                           for c in part)):
                raise mg.StageError("Non-portable archive path component")
        if unicodedata.normalize("NFC", name) != name:
            raise mg.StageError("Archive path is not NFC-normalised")
        return name

    def claim(self, name: str, is_file: bool) -> None:
        parts = name.split("/")
        for i in range(1, len(parts) + 1):  # one exact spelling per folded path
            prefix = "/".join(parts[:i])
            if self.spelling.setdefault(prefix.casefold(), prefix) != prefix:
                raise mg.StageError("Archive paths collide by case")
        for i in range(1, len(parts)):  # every ancestor must be a directory
            if self.folded.setdefault("/".join(parts[:i]).casefold(), False):
                raise mg.StageError("Archive path nests under a file")
        key = name.casefold()
        if key in self.folded and (is_file or self.folded[key]):
            raise mg.StageError("Duplicate or case-colliding archive paths")
        self.folded[key] = is_file

    def budget(self, size: int) -> None:
        if not 0 <= size <= mg.MAX_FILE_BYTES:
            raise mg.StageError("Archive member has an invalid or oversized length")
        self.files += 1
        self.total += size
        if self.files > mg.MAX_FILES or self.total > mg.MAX_TOTAL_BYTES:
            raise mg.StageError("Archive exceeds the staging file/byte budget")


def _write(reader, dest: Path, size: int, executable: bool) -> str:
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if shutil.disk_usage(dest.parent).free < size:
        raise mg.StageError("Insufficient free space to unpack the archive")
    digest, read = hashlib.sha256(), 0
    with dest.open("xb") as out:
        while True:
            block = reader.read(min(mg.BUFFER, size + 1 - read))
            if not block:
                break
            read += len(block)
            if read > size:
                raise mg.StageError("Archive member is longer than declared")
            digest.update(block)
            out.write(block)
        if os.name != "nt":
            os.fchmod(out.fileno(), 0o700 if executable else 0o600)
        out.flush()
        os.fsync(out.fileno())
    if read != size:
        raise mg.StageError("Archive member is truncated")
    return digest.hexdigest()


def _tar(archive: Path, scratch: Path, plan: _Plan) -> dict:
    entries: dict = {}
    try:
        with tarfile.open(archive, "r:*") as tar:
            for member in tar:
                plan.count()
                name = plan.name(member.name)
                if name is None or member.isdir():
                    if name is not None:
                        plan.claim(name, False)
                    continue
                if not member.isreg():  # symlink, hardlink, device, fifo, ...
                    raise mg.StageError("Archive contains a link or special file")
                plan.claim(name, True)
                plan.budget(member.size)
                reader = tar.extractfile(member)
                if reader is None:
                    raise mg.StageError("Archive member cannot be read")
                digest = _write(reader, scratch.joinpath(*name.split("/")),
                                member.size, bool(member.mode & 0o100))
                entries[name] = {"size": member.size, "sha256": digest}
            # Drain the tail so a truncated/corrupt compression trailer (CRC)
            # fails here; bounded because the tail is attacker-controlled.
            tail = 0
            while block := tar.fileobj.read(mg.BUFFER):
                tail += len(block)
                if tail > 16 * mg.BUFFER:
                    raise mg.StageError("Archive has excessive trailing data")
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        if isinstance(exc, mg.StageError):
            raise
        raise mg.StageError(f"Unreadable or corrupt tar archive: {type(exc).__name__}") from exc
    return entries


def _zip(archive: Path, scratch: Path, plan: _Plan) -> dict:
    entries: dict = {}
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > mg.MAX_FILES * 2:
                raise mg.StageError("Archive has too many entries")
            for info in infos:
                plan.count()
                name = plan.name(info.filename)
                mode = info.external_attr >> 16
                if info.flag_bits & 0x1:
                    raise mg.StageError("Encrypted archive member")
                if stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise mg.StageError("Archive contains a link or special file")
                if name is None or info.is_dir():
                    if name is not None:
                        plan.claim(name, False)
                    continue
                if (info.file_size > RATIO_FLOOR
                        and info.file_size > MAX_RATIO * max(1, info.compress_size)):
                    raise mg.StageError("Archive member has a suspicious compression ratio")
                plan.claim(name, True)
                plan.budget(info.file_size)
                with bundle.open(info) as reader:
                    digest = _write(reader, scratch.joinpath(*name.split("/")),
                                    info.file_size, bool(mode & 0o100))
                entries[name] = {"size": info.file_size, "sha256": digest}
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, UnicodeError) as exc:
        if isinstance(exc, mg.StageError):
            raise
        raise mg.StageError(f"Unreadable or corrupt zip archive: {type(exc).__name__}") from exc
    return entries


def unpack_archive(archive: Path, scratch: Path, *,
                   strip_prefix: str | None = None) -> dict[str, dict]:
    """Unpack *archive* into the NEW private directory *scratch*.

    Returns a manifest for ``managed_generations.stage_local_snapshot``.
    On any failure *scratch* is removed and :class:`StageError` is raised.
    """
    archive, scratch = Path(archive), Path(scratch)
    if archive.is_symlink() or not archive.is_file():
        raise mg.StageError("Archive must be an ordinary file")
    if scratch.exists() or scratch.is_symlink():
        raise mg.StageError("Unpack target must be new")
    scratch.mkdir(mode=0o700, parents=True)
    try:
        plan = _Plan(strip_prefix)
        if tarfile.is_tarfile(archive):
            entries = _tar(archive, scratch, plan)
        elif zipfile.is_zipfile(archive):
            entries = _zip(archive, scratch, plan)
        else:
            raise mg.StageError("Unsupported archive format")
        if not entries:
            raise mg.StageError("Archive contains no files")
        return entries
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
