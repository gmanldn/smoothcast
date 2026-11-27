"""Always-current local library index with a replication changelog (issue #408).

Video **and** audio, bounded tags, quick content keys and an append-only
changelog (``seq``) so peers can replicate the shared set
(docs/MESH_SEARCH.md sections 1-2). GTK-free; one writer thread per indexer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
from typing import Callable

import fingerprint
import library_folders
import media_names
import search_engine
import media_tools
import task_runtime

VIDEO_EXT = {".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mpeg", ".mpg", ".wmv"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".aif", ".aiff", ".wma"}
MAX_ENTRIES = 200_000
MAX_STRING = 512
MISSING_GRACE_SECONDS = 24 * 3600
CHANGELOG_KEEP_ROWS = 100_000
CHANGELOG_KEEP_SECONDS = 7 * 24 * 3600
SCHEMA = 1
DEFAULT_DB = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "smoothcast" / "library_v2.sqlite3"

ENTRY_COLUMNS = ("content_key", "folder_id", "rel_path", "kind", "title", "sort_title", "year",
                 "show", "season", "episode", "artist", "album_artist", "album", "disc", "track",
                 "genre", "duration", "width", "height", "langs", "size", "mtime_ns", "ino")


class StaleGeneration(RuntimeError):
    """The caller's epoch or sequence cannot be served incrementally."""


def _open(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if db.is_symlink():
        raise RuntimeError("Refusing a symbolic link as the library database")
    connection = sqlite3.connect(db, timeout=5, check_same_thread=False)
    if os.name == "posix":
        try:
            os.chmod(db, 0o600)
        except OSError:
            pass
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            content_key TEXT PRIMARY KEY, folder_id TEXT NOT NULL, rel_path TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, sort_title TEXT NOT NULL, year INTEGER,
            show TEXT, season INTEGER, episode INTEGER, artist TEXT, album_artist TEXT, album TEXT,
            disc INTEGER, track INTEGER, genre TEXT, duration REAL, width INTEGER, height INTEGER,
            langs TEXT, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, ino TEXT,
            updated_seq INTEGER NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS entries_path ON entries(folder_id, rel_path);
        CREATE TABLE IF NOT EXISTS changelog (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, content_key TEXT NOT NULL,
            op TEXT NOT NULL, folder_id TEXT NOT NULL, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS folder_state (folder_id TEXT PRIMARY KEY, missing_since REAL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    return connection


def _clip(value: object) -> str | None:
    return str(value).strip()[:MAX_STRING] if value not in (None, "") else None


def _num(value: object) -> int | None:
    try:
        return int(str(value).split("/")[0])
    except (TypeError, ValueError):
        return None


def probe_tags(path: Path) -> dict:
    """Bounded, network-disabled ffprobe; returns {} when unavailable."""
    if not media_tools.find_media_tool("ffprobe"):
        return {}
    args = [media_tools.resolve_media_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries",
            "format=duration:format_tags:stream=codec_type,width,height:stream_tags=language",
            "-of", "json", "-i", str(path)]
    try:
        with tempfile.TemporaryFile() as out:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.DEVNULL, timeout=12, check=False)
            if result.returncode:
                return {}
            out.seek(0)
            raw = out.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                return {}
            data = json.loads(raw.decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build_entry(folder: library_folders.LibraryFolder, rel: str, info: os.stat_result,
                key: str, probe: dict) -> dict:
    name = Path(rel).name
    suffix = Path(rel).suffix.lower()
    raw_fmt = probe.get("format")
    fmt: dict = raw_fmt if isinstance(raw_fmt, dict) else {}
    raw_tags = fmt.get("tags")
    tags = {str(k).lower(): v for k, v in raw_tags.items()} if isinstance(raw_tags, dict) else {}
    streams = [s for s in probe.get("streams", []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    langs = sorted({str((s.get("tags") or {}).get("language"))[:8] for s in streams
                    if isinstance(s.get("tags"), dict) and (s["tags"].get("language") or "") not in ("", "und")})
    kind = "music" if suffix in AUDIO_EXT else "video"
    parent = Path(rel).parent.name
    episode = media_names.parse_episode(name, parent) if kind == "video" else None
    title = _clip(tags.get("title")) or media_names.clean_title(name)
    duration: float | None
    try:
        duration = float(fmt["duration"]) if fmt.get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None
    show = episode[0] if episode and episode[0] else (parent if episode else None)
    return {
        "content_key": key, "folder_id": folder.id, "rel_path": rel, "kind": kind,
        "title": title, "sort_title": title.casefold(),
        "year": _num(tags.get("date")) or media_names.parse_year(name),
        "show": _clip(show), "season": episode[1] if episode else None,
        "episode": episode[2] if episode else None,
        "artist": _clip(tags.get("artist")), "album_artist": _clip(tags.get("album_artist")),
        "album": _clip(tags.get("album")), "disc": _num(tags.get("disc")),
        "track": _num(tags.get("track")), "genre": _clip(tags.get("genre")),
        "duration": duration, "width": _num(video.get("width")), "height": _num(video.get("height")),
        "langs": ",".join(langs)[:MAX_STRING] or None, "size": info.st_size,
        "mtime_ns": info.st_mtime_ns, "ino": str(info.st_ino),
    }


class LibraryIndexer:
    def __init__(self, db: Path = DEFAULT_DB, *, clock: Callable[[], float] = time.time,
                 busy: Callable[[], bool] = lambda: False,
                 probe: Callable[[Path], dict] = probe_tags) -> None:
        self.db_path = Path(db)
        self.clock, self.busy, self.probe = clock, busy, probe
        self._lock = threading.RLock()
        self._conn = _open(self.db_path)
        self._folders: list[library_folders.LibraryFolder] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._scope: task_runtime.Scope | None = None
        self.rescan_seconds = 15 * 60
        with self._lock:
            search_engine.ensure_schema(self._conn)
            if self._meta("epoch") is None:
                self._set_meta("epoch", secrets.token_hex(8))
                self._set_meta("origin_id", "o_" + secrets.token_hex(8))
                self._set_meta("oldest_seq", "0")

    # -- meta / generation ------------------------------------------------
    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))
        self._conn.commit()

    def generation(self) -> tuple[str, str, int]:
        with self._lock:
            seq = self._conn.execute("SELECT COALESCE(MAX(seq),0) FROM changelog").fetchone()[0]
            return str(self._meta("origin_id")), str(self._meta("epoch")), int(
                max(seq, int(self._meta("oldest_seq") or 0)))

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def _is_shared(self, folder_id: str) -> bool:
        folder = next((f for f in self._folders if f.id == folder_id), None)
        return bool(folder and folder.shared)

    def folder_label(self, folder_id: str) -> str:
        folder = next((f for f in self._folders if f.id == folder_id), None)
        return folder.label if folder else ""

    def _log(self, key: str, op: str, folder_id: str) -> int:
        if op == "upsert" and not self._is_shared(folder_id):
            return 0  # unshared entries never enter the replication stream
        cursor = self._conn.execute(
            "INSERT INTO changelog(content_key, op, folder_id, at) VALUES(?,?,?,?)",
            (key, op, folder_id, self.clock()))
        return int(cursor.lastrowid or 0)

    def search(self, text: object, limit: int = 50, cursor: str | None = None) -> dict:
        with self._lock:
            return search_engine.search(self._conn, text, limit, cursor)

    def resolve_path(self, key: object) -> Path | None:
        """Readable regular file for a shared entry, contained in its library root."""
        entry = self.entry(key) if isinstance(key, str) else None
        folder = next((f for f in self._folders if entry and f.id == entry["folder_id"]), None)
        if entry is None or folder is None or not folder.shared:
            return None
        root = Path(os.path.realpath(folder.path))
        path = Path(os.path.realpath(root / entry["rel_path"]))
        try:
            path.relative_to(root)
            info = path.stat()
        except (OSError, ValueError):
            return None
        import stat as _stat
        return path if _stat.S_ISREG(info.st_mode) and os.access(path, os.R_OK) else None

    def search_rows(self, text: object, limit: int = 50) -> list[dict]:
        """Ranked local rows (shared folders only) for peers' live queries."""
        with self._lock:
            rows, _partial = search_engine.run(self._conn, text, limit)
            return [r for r in rows[:limit] if self._is_shared(r["folder_id"])]

    # -- reads for replication / search ----------------------------------
    def entry(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {','.join(ENTRY_COLUMNS)} FROM entries WHERE content_key=?", (key,)).fetchone()
        return dict(zip(ENTRY_COLUMNS, row)) if row else None

    def changes_since(self, epoch: str, seq: int, limit: int = 5000) -> list[dict]:
        with self._lock:
            if epoch != self._meta("epoch") or seq < int(self._meta("oldest_seq") or 0):
                raise StaleGeneration("epoch changed or history compacted")
            rows = self._conn.execute(
                "SELECT seq, content_key, op FROM changelog WHERE seq>? ORDER BY seq LIMIT ?",
                (seq, max(1, min(limit, 5000)))).fetchall()
            return [{"seq": s, "op": op, "content_key": key,
                     **({"entry": self.entry(key)} if op == "upsert" else {})}
                    for s, key, op in rows]

    def snapshot_page(self, cursor: str | None, limit: int = 5000, *, shared_only: bool = False
                      ) -> tuple[list[dict], str | None, tuple[str, str, int]]:
        limit = max(1, min(limit, 5000))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {','.join(ENTRY_COLUMNS)} FROM entries WHERE content_key>? "
                "ORDER BY content_key LIMIT ?", (cursor or "", limit)).fetchall()
            items = [dict(zip(ENTRY_COLUMNS, row)) for row in rows]
            next_cursor = items[-1]["content_key"] if len(items) == limit else None
            if shared_only:
                items = [i for i in items if self._is_shared(i["folder_id"])]
            return items, next_cursor, self.generation()

    def compact(self) -> None:
        now = self.clock()
        with self._lock:
            newest = self._conn.execute("SELECT COALESCE(MAX(seq),0) FROM changelog").fetchone()[0]
            cutoff = newest - CHANGELOG_KEEP_ROWS
            cursor = self._conn.execute(
                "DELETE FROM changelog WHERE seq<=? AND at<?", (cutoff, now - CHANGELOG_KEEP_SECONDS))
            if cursor.rowcount:
                oldest = self._conn.execute("SELECT COALESCE(MIN(seq),1) FROM changelog").fetchone()[0] - 1
                self._set_meta("oldest_seq", str(max(oldest, int(self._meta("oldest_seq") or 0))))
            self._conn.commit()

    # -- scanning ---------------------------------------------------------
    def set_folders(self, folders: list[library_folders.LibraryFolder]) -> None:
        with self._lock:
            before = {f.id: f.shared for f in self._folders}
            self._folders = list(folders)
            new = {f.id for f in folders}
            for gone in set(before) - new:
                self._drop_folder(gone)
            for folder in folders:
                if folder.id in before and before[folder.id] != folder.shared:
                    op = "upsert" if folder.shared else "delete"
                    for (key,) in self._conn.execute(
                            "SELECT content_key FROM entries WHERE folder_id=?", (folder.id,)).fetchall():
                        self._conn.execute(
                            "INSERT INTO changelog(content_key, op, folder_id, at) VALUES(?,?,?,?)",
                            (key, op, folder.id, self.clock()))
                    self._conn.commit()
        self._wake.set()

    def _drop_folder(self, folder_id: str) -> None:
        rows = self._conn.execute(
            "SELECT content_key FROM entries WHERE folder_id=?", (folder_id,)).fetchall()
        for (key,) in rows:
            self._conn.execute("DELETE FROM entries WHERE content_key=?", (key,))
            self._log(key, "delete", folder_id)
        self._conn.execute("DELETE FROM folder_state WHERE folder_id=?", (folder_id,))
        self._conn.commit()

    def scan_all(self) -> dict:
        totals = {"added": 0, "removed": 0, "skipped": 0, "missing": 0}
        for folder in list(self._folders):
            if self._stop.is_set():
                break
            result = self.scan_folder(folder)
            for k in totals:
                totals[k] += result.get(k, 0)
        self.compact()
        return totals

    def _walk(self, root: Path) -> tuple[list[tuple[str, os.stat_result]], bool]:
        found: list[tuple[str, os.stat_result]] = []
        complete = True
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for item in entries:
                        try:
                            if item.is_symlink():
                                continue
                            if item.is_dir(follow_symlinks=False):
                                stack.append(Path(item.path))
                            elif item.is_file(follow_symlinks=False) and \
                                    Path(item.name).suffix.lower() in VIDEO_EXT | AUDIO_EXT:
                                found.append((os.path.relpath(item.path, root).replace(os.sep, "/"),
                                              item.stat(follow_symlinks=False)))
                        except OSError:
                            complete = False
            except OSError:
                complete = False
        return found, complete

    def scan_folder(self, folder: library_folders.LibraryFolder) -> dict:
        result = {"added": 0, "removed": 0, "skipped": 0, "missing": 0}
        root = Path(folder.path)
        now = self.clock()
        with self._lock:
            if not root.is_dir():
                row = self._conn.execute(
                    "SELECT missing_since FROM folder_state WHERE folder_id=?", (folder.id,)).fetchone()
                since = row[0] if row and row[0] is not None else now
                self._conn.execute("INSERT OR REPLACE INTO folder_state VALUES(?,?)", (folder.id, since))
                self._conn.commit()
                if now - since > MISSING_GRACE_SECONDS:
                    self._drop_folder(folder.id)
                result["missing"] = 1
                return result
            self._conn.execute("INSERT OR REPLACE INTO folder_state VALUES(?,NULL)", (folder.id,))
            known = {(r[0]): (r[1], r[2], r[3], r[4]) for r in self._conn.execute(
                "SELECT rel_path, size, mtime_ns, ino, content_key FROM entries WHERE folder_id=?",
                (folder.id,))}
        found, complete = self._walk(root)
        seen: set[str] = set()
        for rel, info in found:
            if self._stop.is_set():
                return result
            seen.add(rel)
            old = known.get(rel)
            if old and old[:3] == (info.st_size, info.st_mtime_ns, str(info.st_ino)):
                result["skipped"] += 1
                continue
            if self.count() >= MAX_ENTRIES:
                break
            while self.busy() and not self._stop.wait(0.5):
                pass
            path = root / rel
            try:
                key = fingerprint.quick_hash(path)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                    continue  # changed while hashing; retry next pass
                entry = build_entry(folder, rel, info, key, self.probe(path))
            except OSError:
                continue
            with self._lock:
                self._upsert(entry, old[3] if old else None)
            result["added"] += 1
        if complete:
            with self._lock:
                for rel, (_s, _m, _i, key) in known.items():
                    if rel not in seen:
                        self._conn.execute("DELETE FROM entries WHERE content_key=?", (key,))
                        self._log(key, "delete", folder.id)
                        result["removed"] += 1
                self._conn.commit()
        return result

    def _upsert(self, entry: dict, old_key: str | None) -> None:
        try:
            self._upsert_locked(entry, old_key)
        except BaseException:  # noqa: BLE001 - roll back then re-raise
            self._conn.rollback()  # entry and changelog row commit together or not at all
            raise

    def _upsert_locked(self, entry: dict, old_key: str | None) -> None:
        if old_key and old_key != entry["content_key"]:
            self._conn.execute("DELETE FROM entries WHERE content_key=?", (old_key,))
            self._log(old_key, "delete", entry["folder_id"])
        incumbent = self._conn.execute(
            "SELECT folder_id, rel_path FROM entries WHERE content_key=?", (entry["content_key"],)).fetchone()
        if incumbent and tuple(incumbent) != (entry["folder_id"], entry["rel_path"]) \
                and tuple(incumbent) < (entry["folder_id"], entry["rel_path"]):
            self._conn.commit()
            return  # identical bytes elsewhere: the lowest path keeps the entry
        seq = self._log(entry["content_key"], "upsert", entry["folder_id"])
        columns = (*ENTRY_COLUMNS, "updated_seq")
        self._conn.execute(
            f"INSERT OR REPLACE INTO entries({','.join(columns)}) VALUES({','.join('?' * len(columns))})",
            (*[entry[c] for c in ENTRY_COLUMNS], seq))
        self._conn.commit()

    # -- service ----------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._scope = task_runtime.shared().scope()
        self._thread = task_runtime.shared().spawn_daemon(
            "library-indexer", self._scope, self._run, thread_name="library-indexer")

    def _run(self, scope: task_runtime.Scope) -> None:
        while not self._stop.is_set() and not scope.cancelled:
            try:
                self.scan_all()
            except Exception:  # Never let indexing take the app down.  # noqa: BLE001 - indexing must never take the app down
                pass
            waited = 0.0
            while (waited < self.rescan_seconds and not self._wake.is_set()
                   and not scope.cancelled and not self._stop.is_set()):
                self._wake.wait(min(1.0, self.rescan_seconds - waited))
                waited += 1.0
            self._wake.clear()
        self._stop.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._scope is not None:
            self._scope.cancel()
        if self._thread:
            self._thread.join(timeout)
