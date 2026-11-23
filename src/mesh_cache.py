"""Persistent, bounded, privacy-safe mesh metadata cache (ticket #401, "M8").

Remembers peers and targets so the UI can show the whole home instantly at
start (as *cached*, never actionable until confirmed live) and so routing can
prefer targets that have worked. SQLite in WAL mode, mode 0600 in a 0700
directory, schema-versioned, TTL- and LRU-bounded.

Never stored: PINs, cookies, session or CSRF tokens, media paths or titles,
guest/client names, addresses, shared-source summaries. Peers keep only a name,
version and capability names; targets keep identity, name, model, formats and
reliability counters.

Calls are synchronous and lock-protected: run them on a worker (``async_jobs``),
never on the GTK thread. GTK-free. Design: docs/MESH_DESIGN.md.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import threading
import time

import mesh_model as mm
from mesh_state import MeshView

SCHEMA_VERSION = 1
PEER_TTL_S = 7 * 86400
TARGET_TTL_S = 30 * 86400
MAX_PEERS = 512
MAX_TARGETS = 2048
MAX_EDGES = 8192
MAX_QUARANTINED = 2
MIN_RELIABILITY_SAMPLES = 3
PRUNE_EVERY_WRITES = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS peers (
  node_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
  capabilities TEXT NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS targets (
  target_id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, model TEXT NOT NULL,
  formats TEXT NOT NULL, last_state TEXT NOT NULL, first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL, ok_count INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS edges (
  node_id TEXT NOT NULL, target_id TEXT NOT NULL, ok_count INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0, rtt_ms INTEGER, last_seen INTEGER NOT NULL,
  PRIMARY KEY (node_id, target_id));
CREATE INDEX IF NOT EXISTS peers_seen ON peers(last_seen);
CREATE INDEX IF NOT EXISTS targets_seen ON targets(last_seen);
CREATE INDEX IF NOT EXISTS edges_seen ON edges(last_seen);
"""


@dataclass(frozen=True)
class CachedPeer:
    node_id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    first_seen: int
    last_seen: int
    cached: bool = True


@dataclass(frozen=True)
class CachedTarget:
    target_id: str
    kind: str
    name: str
    model: str
    formats: tuple[str, ...]
    last_state: str
    last_seen: int
    reliability: float | None
    cached: bool = True


@dataclass(frozen=True)
class CachedMesh:
    peers: tuple[CachedPeer, ...]
    targets: tuple[CachedTarget, ...]
    last_primary: str


class MeshCache:
    def __init__(self, path: str | os.PathLike[str], *,
                 wall: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._wall = wall
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._writes = 0
        self.recovered = False          # True when a corrupt file was quarantined

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> MeshCache:
        with self._lock:
            if self._db is not None:
                return self
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._chmod(self.path.parent, 0o700)
            try:
                self._db = self._connect()
            except sqlite3.DatabaseError:
                self._quarantine()
                self._db = self._connect()
            self._prune_locked()
            return self

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                finally:
                    self._db = None

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise sqlite3.DatabaseError("cache is from a newer SmoothCast")
            db.executescript(_SCHEMA)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.commit()
        except BaseException:
            db.close()
            raise
        for suffix in ("", "-wal", "-shm"):
            self._chmod(Path(str(self.path) + suffix), 0o600)
        return db

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name == "posix":
            try:
                os.chmod(path, mode)
            except OSError:
                pass

    def _quarantine(self) -> None:
        self.recovered = True
        stamp = int(self._wall())
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.path) + suffix)
            if source.exists():
                try:
                    if suffix == "":
                        source.rename(self.path.with_name(f"{self.path.name}.corrupt-{stamp}"))
                    else:
                        source.unlink()
                except OSError:
                    pass
        old = sorted(self.path.parent.glob(self.path.name + ".corrupt-*"))
        for stale in old[:-MAX_QUARANTINED]:
            try:
                stale.unlink()
            except OSError:
                pass

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("mesh cache is not open")
        return self._db

    # -- writes ---------------------------------------------------------------
    def record_view(self, view: MeshView) -> None:
        """Upsert peers, targets and edge statistics from a live view."""
        now = int(self._wall())
        with self._lock:
            db = self._conn()
            for record in view.nodes:
                if record.node_id == view.local_id:
                    continue
                db.execute(
                    "INSERT INTO peers(node_id,name,version,capabilities,first_seen,last_seen)"
                    " VALUES(?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET name=excluded.name,"
                    " version=excluded.version, capabilities=excluded.capabilities,"
                    " last_seen=excluded.last_seen",
                    (record.node_id, record.name, record.version,
                     ",".join(record.capabilities), now, now))
            edges = {(r.node_id, e.peer): e for r in view.nodes for e in r.edges
                     if e.peer_kind == "target"}
            for node_id, target in view.targets():
                ok = 1 if target.state == "ready" else 0
                bad = 1 if target.state == "unreachable" else 0
                db.execute(
                    "INSERT INTO targets(target_id,kind,name,model,formats,last_state,"
                    "first_seen,last_seen,ok_count,fail_count) VALUES(?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(target_id) DO UPDATE SET kind=excluded.kind,"
                    " name=excluded.name, model=excluded.model, formats=excluded.formats,"
                    " last_state=excluded.last_state, last_seen=excluded.last_seen,"
                    " ok_count=ok_count+?, fail_count=fail_count+?",
                    (target.id, target.kind, target.name, target.model,
                     ",".join(target.formats), target.state, now, now, ok, bad, ok, bad))
                edge = edges.get((node_id, target.id))
                db.execute(
                    "INSERT INTO edges(node_id,target_id,ok_count,fail_count,rtt_ms,last_seen)"
                    " VALUES(?,?,?,?,?,?) ON CONFLICT(node_id,target_id) DO UPDATE SET"
                    " ok_count=ok_count+?, fail_count=fail_count+?,"
                    " rtt_ms=COALESCE(excluded.rtt_ms, rtt_ms), last_seen=excluded.last_seen",
                    (node_id, target.id, ok, bad, edge.rtt_ms if edge else None, now, ok, bad))
            db.commit()
            self._writes += 1
            if self._writes % PRUNE_EVERY_WRITES == 0:
                self._prune_locked()
            else:
                self._cap_locked()

    def set_last_primary(self, node_id: str) -> None:
        if not isinstance(node_id, str) or len(node_id) != 32:
            return
        with self._lock:
            db = self._conn()
            db.execute("INSERT INTO meta(key,value) VALUES('last_primary',?)"
                       " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (node_id,))
            db.commit()

    def forget(self) -> None:
        """Forget network: delete the database and every sidecar file atomically."""
        with self._lock:
            self.close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(str(self.path) + suffix).unlink()
                except FileNotFoundError:
                    pass
            for stale in self.path.parent.glob(self.path.name + ".corrupt-*"):
                try:
                    stale.unlink()
                except OSError:
                    pass

    # -- bounds ------------------------------------------------------------------
    def _prune_locked(self) -> None:
        db = self._conn()
        now = int(self._wall())
        db.execute("DELETE FROM peers WHERE last_seen < ?", (now - PEER_TTL_S,))
        db.execute("DELETE FROM targets WHERE last_seen < ?", (now - TARGET_TTL_S,))
        db.execute("DELETE FROM edges WHERE last_seen < ?", (now - TARGET_TTL_S,))
        db.commit()
        self._cap_locked()

    def _cap_locked(self) -> None:
        db = self._conn()
        for table, key, cap in (("peers", "node_id", MAX_PEERS),
                                ("targets", "target_id", MAX_TARGETS)):
            db.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT {key} FROM {table}"
                       f" ORDER BY last_seen DESC LIMIT -1 OFFSET ?)", (cap,))
        db.execute("DELETE FROM edges WHERE rowid IN (SELECT rowid FROM edges"
                   " ORDER BY last_seen DESC LIMIT -1 OFFSET ?)", (MAX_EDGES,))
        db.commit()

    # -- reads -----------------------------------------------------------------------
    def load(self) -> CachedMesh:
        """Everything remembered, newest first. All entries are ``cached=True``."""
        with self._lock:
            db = self._conn()
            peers = tuple(CachedPeer(
                node_id, name, version, tuple(c for c in caps.split(",") if c),
                first, last) for node_id, name, version, caps, first, last in db.execute(
                "SELECT node_id,name,version,capabilities,first_seen,last_seen FROM peers"
                " ORDER BY last_seen DESC, node_id"))
            targets = tuple(CachedTarget(
                tid, kind, name, model, tuple(f for f in formats.split(",") if f), state,
                last, self._ratio(ok, bad))
                for tid, kind, name, model, formats, state, last, ok, bad in db.execute(
                    "SELECT target_id,kind,name,model,formats,last_state,last_seen,ok_count,"
                    "fail_count FROM targets ORDER BY last_seen DESC, target_id"))
            row = db.execute("SELECT value FROM meta WHERE key='last_primary'").fetchone()
            return CachedMesh(peers, targets, row[0] if row else "")

    @staticmethod
    def _ratio(ok: int, bad: int) -> float | None:
        total = ok + bad
        return None if total < MIN_RELIABILITY_SAMPLES else ok / total

    def reliability(self, target_id: str) -> float | None:
        with self._lock:
            row = self._conn().execute(
                "SELECT ok_count, fail_count FROM targets WHERE target_id=?",
                (target_id,)).fetchone()
            return None if row is None else self._ratio(*row)

    def edge_stats(self, node_id: str, target_id: str) -> tuple[float | None, int | None]:
        """(success ratio, last rtt) for a node reaching a target, from history."""
        with self._lock:
            row = self._conn().execute(
                "SELECT ok_count, fail_count, rtt_ms FROM edges WHERE node_id=? AND target_id=?",
                (node_id, target_id)).fetchone()
            return (None, None) if row is None else (self._ratio(row[0], row[1]), row[2])

    def counts(self) -> dict[str, int]:
        with self._lock:
            db = self._conn()
            return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("peers", "targets", "edges")}

    def known_target_ids(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._conn().execute("SELECT target_id FROM targets")}


def cached_records(cache: CachedMesh, live_ids: set[str]) -> list[mm.NodeRecord]:
    """Placeholder records (``name`` only) for UI warm start; live peers are skipped."""
    return [mm.NodeRecord(node_id=p.node_id, boot_id="0" * 32, name=p.name, version=p.version,
                          capabilities=p.capabilities)
            for p in cache.peers if p.node_id not in live_ids]


__all__ = ["CachedMesh", "CachedPeer", "CachedTarget", "MeshCache", "cached_records"]
