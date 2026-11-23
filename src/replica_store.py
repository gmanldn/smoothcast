"""SQLite store for peers' replicated shared libraries (issue #411).

One read-only replica per origin, written only by ``replica_manager``. Every
page is applied in a single transaction so a crash never leaves half a page.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import time

MAX_ORIGINS = 16
MAX_ENTRIES_PER_ORIGIN = 200_000
MAX_DB_BYTES = 150 * 1024 * 1024
FIELDS = ("content_key", "kind", "title", "sort_title", "year", "show", "season", "episode",
          "artist", "album_artist", "album", "disc", "track", "genre", "duration",
          "width", "height", "langs", "size", "folder_label", "rel_path")
DEFAULT_DB = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "smoothcast" / "replicas.sqlite3"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS origins (
    origin_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', epoch TEXT, seq INTEGER NOT NULL DEFAULT 0,
    entry_count INTEGER NOT NULL DEFAULT 0, last_synced_at REAL, last_seen_at REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'stale', snapshot_epoch TEXT, snapshot_cursor TEXT,
    snapshot_at_seq INTEGER, snapshot_active INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0, backoff_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rentries (
    origin_id TEXT NOT NULL, {', '.join(f + (' INTEGER' if f in ('year','season','episode','disc','track','width','height','size') else ' REAL' if f == 'duration' else ' TEXT') for f in FIELDS)},
    PRIMARY KEY (origin_id, content_key));
PRAGMA recursive_triggers=ON;
CREATE VIRTUAL TABLE IF NOT EXISTS rentries_fts USING fts5(
    title, show, artist, album, album_artist, genre,
    content='rentries', tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS rentries_tri USING fts5(
    sort_title, content='rentries', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS rentries_ai AFTER INSERT ON rentries BEGIN
  INSERT INTO rentries_fts(rowid,title,show,artist,album,album_artist,genre)
    VALUES(new.rowid,new.title,new.show,new.artist,new.album,new.album_artist,new.genre);
  INSERT INTO rentries_tri(rowid,sort_title) VALUES(new.rowid,new.sort_title);
END;
CREATE TRIGGER IF NOT EXISTS rentries_ad AFTER DELETE ON rentries BEGIN
  INSERT INTO rentries_fts(rentries_fts,rowid,title,show,artist,album,album_artist,genre)
    VALUES('delete',old.rowid,old.title,old.show,old.artist,old.album,old.album_artist,old.genre);
  INSERT INTO rentries_tri(rentries_tri,rowid,sort_title) VALUES('delete',old.rowid,old.sort_title);
END;
"""


class ReplicaStore:
    def __init__(self, path: Path = DEFAULT_DB, *, clock=time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.recovered = False
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.conn = self._open()

    def _open(self) -> sqlite3.Connection:
        try:
            conn = self._connect()
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("quick_check failed")
            return conn
        except sqlite3.DatabaseError:
            try:
                self.conn.close()
            except Exception:
                pass
            if self.path.exists():
                self.path.rename(self.path.with_name(
                    f"{self.path.name}.corrupt-{int(self.clock())}"))
            self.recovered = True
            return self._connect()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        if os.name == "posix":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        conn.executescript(SCHEMA)
        conn.commit()
        self.conn = conn
        return conn

    # -- origins ----------------------------------------------------------
    def origin(self, origin_id: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM origins WHERE origin_id=?", (origin_id,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row)) if row else None

    def origins(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM origins ORDER BY name, origin_id")
        names = [c[0] for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def touch_origin(self, origin_id: str, name: str, now: float) -> None:
        if self.origin(origin_id) is None:
            if len(self.origins()) >= MAX_ORIGINS:
                oldest = self.conn.execute(
                    "SELECT origin_id FROM origins ORDER BY last_seen_at LIMIT 1").fetchone()
                if oldest:
                    self.delete_origin(oldest[0])
            self.conn.execute("INSERT INTO origins(origin_id,name,last_seen_at) VALUES(?,?,?)",
                              (origin_id, name[:80], now))
        else:
            self.conn.execute("UPDATE origins SET name=?, last_seen_at=? WHERE origin_id=?",
                              (name[:80] or "", now, origin_id))
        self.conn.commit()

    def set_state(self, origin_id: str, state: str) -> None:
        self.conn.execute("UPDATE origins SET state=? WHERE origin_id=?", (state, origin_id))
        self.conn.commit()

    def record_failure(self, origin_id: str, now: float) -> float:
        row = self.origin(origin_id)
        fails = (row["fail_count"] if row else 0) + 1
        wait = min(3600.0, 60.0 * 2 ** (fails - 1))
        self.conn.execute("UPDATE origins SET fail_count=?, backoff_until=? WHERE origin_id=?",
                          (fails, now + wait, origin_id))
        self.conn.commit()
        return wait

    def delete_origin(self, origin_id: str) -> None:
        self.conn.execute("DELETE FROM rentries WHERE origin_id=?", (origin_id,))
        self.conn.execute("DELETE FROM origins WHERE origin_id=?", (origin_id,))
        self.conn.commit()

    def reset_origin(self, origin_id: str) -> None:
        """Drop an origin's rows but keep its record (stale epoch, bad data)."""
        self.conn.execute("DELETE FROM rentries WHERE origin_id=?", (origin_id,))
        self.conn.execute(
            "UPDATE origins SET epoch=NULL, seq=0, entry_count=0, snapshot_active=0, "
            "snapshot_cursor=NULL, snapshot_epoch=NULL, snapshot_at_seq=NULL WHERE origin_id=?",
            (origin_id,))
        self.conn.commit()

    # -- applying pages ---------------------------------------------------
    def _count(self, origin_id: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM rentries WHERE origin_id=?", (origin_id,)).fetchone()[0])

    def _put(self, origin_id: str, entry: dict) -> None:
        values = [entry.get(f) for f in FIELDS]
        self.conn.execute(
            f"INSERT OR REPLACE INTO rentries(origin_id,{','.join(FIELDS)}) "
            f"VALUES(?,{','.join('?' * len(FIELDS))})", [origin_id, *values])

    def apply_snapshot_page(self, origin_id: str, epoch: str, entries: list[dict],
                            cursor: str | None, at_seq: int, now: float) -> None:
        """Apply one snapshot page atomically; ``cursor`` None marks the end."""
        try:
            row = self.origin(origin_id) or {}
            if row.get("snapshot_active") and row.get("snapshot_epoch") != epoch:
                self.conn.execute("DELETE FROM rentries WHERE origin_id=?", (origin_id,))
            for entry in entries:
                if self._count(origin_id) >= MAX_ENTRIES_PER_ORIGIN:
                    break
                self._put(origin_id, entry)
            if cursor is None:
                self.conn.execute(
                    "UPDATE origins SET epoch=?, seq=?, snapshot_active=0, snapshot_cursor=NULL, "
                    "snapshot_epoch=NULL, snapshot_at_seq=NULL, last_synced_at=?, fail_count=0, "
                    "backoff_until=0, entry_count=(SELECT COUNT(*) FROM rentries WHERE origin_id=?), "
                    "state='fresh' WHERE origin_id=?", (epoch, at_seq, now, origin_id, origin_id))
            else:
                self.conn.execute(
                    "UPDATE origins SET snapshot_active=1, snapshot_epoch=?, snapshot_cursor=?, "
                    "snapshot_at_seq=? WHERE origin_id=?", (epoch, cursor, at_seq, origin_id))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def apply_changes(self, origin_id: str, epoch: str, changes: list[dict], to_seq: int,
                      now: float) -> None:
        try:
            for change in changes:
                if change["op"] == "upsert":
                    if self._count(origin_id) < MAX_ENTRIES_PER_ORIGIN:
                        self._put(origin_id, change["entry"])
                else:
                    self.conn.execute("DELETE FROM rentries WHERE origin_id=? AND content_key=?",
                                      (origin_id, change["content_key"]))
            self.conn.execute(
                "UPDATE origins SET epoch=?, seq=?, last_synced_at=?, fail_count=0, backoff_until=0, "
                "entry_count=(SELECT COUNT(*) FROM rentries WHERE origin_id=?), state='fresh' "
                "WHERE origin_id=?", (epoch, to_seq, now, origin_id, origin_id))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def keys(self, origin_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT content_key FROM rentries WHERE origin_id=?", (origin_id,))}

    def db_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def evict_least_recently_seen(self) -> str | None:
        row = self.conn.execute("SELECT origin_id FROM origins ORDER BY last_seen_at LIMIT 1").fetchone()
        if row:
            self.delete_origin(row[0])
            return str(row[0])
        return None

    def close(self) -> None:
        self.conn.close()
