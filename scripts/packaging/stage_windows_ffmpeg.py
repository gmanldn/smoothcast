"""Verify and stage a pinned Windows x64 FFmpeg payload (#529). Pure core; downloads are the caller's job.

Reads a checked-in immutable lock description (``packaging/windows-ffmpeg.lock.json``; the real source,
digest and GPL/LGPL decision are an owner/legal gate and are NOT invented here). This module only proves an
archive matches the lock and extracts exactly the allowed files, fail-closed, into a fresh directory that
is renamed into place atomically. Nothing here executes a downloaded binary.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import re
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

TOOLS = ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")
REQUIRED_NOTICES = ("THIRD_PARTY_NOTICES.txt", "LICENSE.txt", "PROVENANCE.txt")
MIN_FFMPEG_MAJOR = 5
MAX_ARCHIVE = 400 * 1024 * 1024
MAX_MEMBER = 300 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,100}\Z")


class StageError(ValueError):
    pass


def validate_lock(lock) -> dict:
    if not isinstance(lock, dict):
        raise StageError("lock must be an object")
    miss = [k for k in ("version", "url", "filename", "sha256", "size", "license", "configure", "tools") if k not in lock]
    if miss:
        raise StageError(f"lock missing: {', '.join(miss)}")
    if not str(lock["url"]).startswith("https://") or not _NAME.match(str(lock["filename"])):
        raise StageError("lock url must be https and filename plain")
    if not isinstance(lock["sha256"], str) or not _SHA.match(lock["sha256"]):
        raise StageError("lock sha256 must be 64 lowercase hex")
    if not isinstance(lock["size"], int) or isinstance(lock["size"], bool) or not 0 < lock["size"] <= MAX_ARCHIVE:
        raise StageError("lock size out of range")
    if sorted(lock["tools"]) != sorted(TOOLS):
        raise StageError("lock must list exactly ffmpeg.exe, ffprobe.exe and ffplay.exe")
    for d in lock.get("dlls", []):
        if not (isinstance(d, str) and _NAME.match(d) and d.lower().endswith(".dll")):
            raise StageError(f"bad dll name: {d!r}")
    return lock


def verify_artifact(data: bytes, lock: dict) -> None:
    if len(data) != lock["size"]:
        raise StageError("archive size does not match the lock (truncated or replaced)")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), lock["sha256"]):
        raise StageError("archive SHA-256 does not match the lock")


def pe_is_x64(data: bytes) -> bool:
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    off = struct.unpack_from("<I", data, 0x3C)[0]
    if off + 6 > len(data) or data[off:off + 4] != b"PE\0\0":
        return False
    return struct.unpack_from("<H", data, off + 4)[0] == 0x8664


def stage(archive: bytes, lock: dict, dest: Path) -> list[str]:
    """Verify then extract only allow-listed members (flattened by basename) into ``dest``. -> staged names."""
    validate_lock(lock)
    verify_artifact(archive, lock)
    allowed = set(TOOLS) | set(lock.get("dlls", [])) | set(REQUIRED_NOTICES) | set(lock.get("extra_files", []))
    dest = Path(dest)
    tmp = Path(tempfile.mkdtemp(prefix=".stage-", dir=dest.parent if dest.parent.exists() else None))
    try:
        try:
            zf = zipfile.ZipFile(io.BytesIO(archive))
        except zipfile.BadZipFile as exc:
            raise StageError("archive is not a valid zip") from exc
        got: dict[str, bytes] = {}
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            p = PurePosixPath(info.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or ":" in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise StageError(f"unsafe archive member: {info.filename!r}")
            base = p.name
            if base not in allowed:
                continue                                  # unexpected files are never installed
            if base in got:
                raise StageError(f"duplicate member: {base}")
            if info.file_size > MAX_MEMBER:
                raise StageError(f"member too large: {base}")
            total += info.file_size
            if total > MAX_ARCHIVE:
                raise StageError("archive expands too large")
            got[base] = zf.read(info)
        for t in TOOLS:
            if t not in got:
                raise StageError(f"missing tool: {t}")
            if not pe_is_x64(got[t]):
                raise StageError(f"{t} is not a Windows x64 executable")
        for d in lock.get("dlls", []):
            if d not in got:
                raise StageError(f"missing declared dll: {d}")
        for n in REQUIRED_NOTICES:
            if n not in got:
                raise StageError(f"missing notice file: {n}")
        for name, blob in got.items():
            (tmp / name).write_bytes(blob)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
        return sorted(got)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)            # no partial staged destination remains
        raise


def parse_major(version_text: str) -> int | None:
    m = re.search(r"(?:ffmpeg|ffprobe|ffplay) version\s+(?:n)?(\d+)\.", version_text or "")
    return int(m.group(1)) if m else None


def check_capabilities(version_text: str, encoders_text: str, filters_text: str, need_encoders=("libx264", "aac"),
                       need_filters=("subtitles", "loudnorm", "aresample")) -> list[str]:
    """Exact missing features (empty = OK). Inputs are captured ``-version``, ``-encoders`` and ``-filters`` output."""
    missing = []
    major = parse_major(version_text)
    if major is None:
        missing.append("version: unreadable")
    elif major < MIN_FFMPEG_MAJOR:
        missing.append(f"version: {major} < {MIN_FFMPEG_MAJOR}")
    words = lambda t: set(re.findall(r"[A-Za-z0-9_]+", t or ""))
    enc, fil = words(encoders_text), words(filters_text)
    missing += [f"encoder: {e}" for e in need_encoders if e not in enc]
    missing += [f"filter: {f}" for f in need_filters if f not in fil]
    return missing
