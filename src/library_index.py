"""Opt-in, bounded-memory media index; no GTK, network or automatic scanning.

Each file's SHA-256 is streamed, only changed files are rehashed, and index
pruning occurs only after a complete, error-free scan of the selected root.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid

EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mpeg", ".mpg", ".wmv"})
CHUNK = 1024 * 1024
MAX_PROBE_BYTES = 256 * 1024
DEFAULT_DB = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "smoothcast" / "library.sqlite3"


class IndexError(RuntimeError):
    """An index input cannot be safely processed."""


def _db_open(db: Path) -> sqlite3.Connection:
    # Local media paths and fingerprints are private. Never leave new cache
    # files world-readable under a permissive umask or follow a cache symlink.
    db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if db.is_symlink():
        raise IndexError("Refusing a symbolic link as the library database")
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(db, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(db, flags | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise IndexError("Library database must be a regular file")
        if os.name == "posix":
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    connection = sqlite3.connect(db, timeout=5)
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("""CREATE TABLE IF NOT EXISTS media (
        path TEXT NOT NULL, root TEXT NOT NULL, size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL, dev INTEGER NOT NULL, inode INTEGER NOT NULL,
        sha256 TEXT NOT NULL, metadata TEXT NOT NULL,
        probed INTEGER NOT NULL DEFAULT 0, scan_id TEXT NOT NULL,
        indexed_at TEXT NOT NULL, PRIMARY KEY (root, path)
    )""")
    # Upgrade early snapshots without dropping an existing personal index.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(media)")}
    if "ctime_ns" not in columns:
        connection.execute("ALTER TABLE media ADD COLUMN ctime_ns INTEGER NOT NULL DEFAULT 0")
    connection.execute("CREATE INDEX IF NOT EXISTS media_root_idx ON media(root)")
    return connection


def _fingerprint(path: Path, expected: os.stat_result) -> str:
    """Hash regular file bytes without following symlinks or buffering media."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise IndexError("Refusing a symbolic link")
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise IndexError("Refusing nonregular media")
        if (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino) != (
                expected.st_size, expected.st_mtime_ns, expected.st_dev, expected.st_ino):
            raise IndexError("Media changed before hashing")
        hasher = hashlib.sha256()
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            hasher.update(block)
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise IndexError("Media changed while hashing")
        return hasher.hexdigest()
    finally:
        os.close(fd)


def _probe(path: Path) -> tuple[dict, bool]:
    """Optional local-only FFprobe; bound runtime and output, never a shell."""
    if not shutil.which("ffprobe"):
        return {"probe_error": "ffprobe not installed"}, False
    args = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=duration,format_name:stream=codec_type,codec_name,width,height,channels",
            "-of", "json", "-i", str(path)]
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=stderr, check=False, timeout=12)
            if result.returncode:
                return {"probe_error": "decoder did not recognise this file"}, False
            stdout.seek(0)
            raw = stdout.read(MAX_PROBE_BYTES + 1)
            if len(raw) > MAX_PROBE_BYTES:
                return {"probe_error": "decoder metadata exceeded output limit"}, False
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("expected an object")
            return {"format": decoded.get("format", {}),
                    "streams": decoded.get("streams", [])}, True
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, TypeError):
        return {"probe_error": "decoder metadata unavailable"}, False


def scan(root: Path, db: Path, *, probe: bool = False, max_files: int = 10000,
         max_dirs: int = 10000, max_depth: int = 16) -> dict:
    """Incremental scan; incomplete scans must never delete cached entries."""
    if min(max_files, max_dirs) < 1 or max_depth < 0:
        raise IndexError("Scan limits must be positive and depth nonnegative")
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise IndexError("Scan root must be a directory")
    root_key = str(root)
    ident = uuid.uuid4().hex
    counts = dict(hashed=0, reused=0, probed=0, errors=0, removed=0, skipped_symlinks=0,
                  files_seen=0, directories_seen=0, complete=True)
    connection = _db_open(Path(db).expanduser())
    try:
        stack = [(root, 0)]
        while stack:
            if counts["directories_seen"] >= max_dirs:
                counts["complete"] = False
                break
            directory, depth = stack.pop()
            counts["directories_seen"] += 1
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                counts["skipped_symlinks"] += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if depth < max_depth:
                                    stack.append((Path(entry.path), depth + 1))
                                else:
                                    counts["complete"] = False
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            path = Path(entry.path)
                            if path.suffix.lower() not in EXTENSIONS:
                                continue
                            if counts["files_seen"] >= max_files:
                                counts["complete"] = False
                                break
                            counts["files_seen"] += 1
                            info = entry.stat(follow_symlinks=False)
                            prior = connection.execute(
                                "SELECT size,mtime_ns,ctime_ns,dev,inode,sha256,metadata,probed FROM media WHERE path=? AND root=?",
                                (str(path), root_key)).fetchone()
                            unchanged = (prior is not None and prior[:5] == (
                                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino))
                            if unchanged:
                                digest, previous_json, probed = prior[5:]
                                metadata = json.loads(previous_json)
                                counts["reused"] += 1
                            else:
                                digest = _fingerprint(path, info)
                                metadata = {}
                                probed = 0
                                counts["hashed"] += 1
                            if probe and not probed:
                                metadata, probed = _probe(path)
                                counts["probed"] += int(bool(probed))
                            connection.execute("""INSERT INTO media (
                                path,root,size,mtime_ns,ctime_ns,dev,inode,sha256,metadata,probed,scan_id,indexed_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(root,path) DO UPDATE SET
                                root=excluded.root,size=excluded.size,mtime_ns=excluded.mtime_ns,
                                ctime_ns=excluded.ctime_ns,
                                dev=excluded.dev,inode=excluded.inode,sha256=excluded.sha256,
                                metadata=excluded.metadata,probed=excluded.probed,
                                scan_id=excluded.scan_id,indexed_at=excluded.indexed_at""",
                                (str(path), root_key, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev,
                                 info.st_ino, digest, json.dumps(metadata, separators=(",", ":")),
                                 int(bool(probed)), ident, datetime.now(timezone.utc).isoformat()))
                        except (OSError, ValueError, sqlite3.DatabaseError, IndexError):
                            counts["errors"] += 1
                            counts["complete"] = False
                    if not counts["complete"] and counts["files_seen"] >= max_files:
                        break
            except OSError:
                counts["errors"] += 1
                counts["complete"] = False
            connection.commit()  # preserve progress if a later directory is unreadable
        if counts["complete"] and counts["errors"] == 0:
            cursor = connection.execute("DELETE FROM media WHERE root=? AND scan_id!=?",
                                        (root_key, ident))
            counts["removed"] = max(0, cursor.rowcount)
        connection.commit()
    finally:
        connection.close()
    return counts | {"root": root_key, "database": str(db)}


def list_media(db: Path, *, limit: int = 100, offset: int = 0) -> list[dict]:
    if not 1 <= limit <= 1000 or offset < 0:
        raise IndexError("List limit must be 1–1000 and offset nonnegative")
    connection = _db_open(Path(db).expanduser())
    try:
        rows = connection.execute(
            "SELECT path,size,mtime_ns,sha256,metadata FROM media ORDER BY path LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [dict(path=p, size=s, mtime_ns=m, sha256=h, metadata=json.loads(j))
                for p, s, m, h, j in rows]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite cache path")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_parser = commands.add_parser("scan", help="Explicitly index a directory; no network or GUI")
    scan_parser.add_argument("directory", type=Path)
    scan_parser.add_argument("--probe", action="store_true", help="Also run offline FFprobe on changed/unprobed media")
    scan_parser.add_argument("--max-files", type=int, default=10000)
    scan_parser.add_argument("--max-dirs", type=int, default=10000)
    scan_parser.add_argument("--max-depth", type=int, default=16)
    list_parser = commands.add_parser("list", help="List cached entries without opening media")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            result = scan(args.directory, args.db, probe=args.probe,
                          max_files=args.max_files, max_dirs=args.max_dirs,
                          max_depth=args.max_depth)
        else:
            result = list_media(args.db, limit=args.limit, offset=args.offset)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if args.command != "scan" or result["complete"] else 1
    except (OSError, sqlite3.DatabaseError, IndexError) as exc:
        print(f"Library index: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
