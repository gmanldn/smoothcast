"""Glue for house-wide library search (issues #411, #412).

``PeerFetcher`` talks to peers' ``/mesh/library/*`` routes over plain HTTP on
the trusted LAN; ``MeshLibrary`` keeps replicas current from live peer
discovery and exposes federated search to the portal.
"""
from __future__ import annotations

import gzip
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import threading
import time
from typing import Callable
from urllib.parse import urlencode, urlsplit

import federated_search
import house_fetch
import library_browse
import lan_guard
import mesh_files
import replica_manager
import replica_store
import search_engine
import base64

TIMEOUT = 2.0
MAX_BODY = 16 * 1024 * 1024


class PeerFetcher:
    """Resolve peer ids to LAN URLs and fetch their library pages."""

    def __init__(self) -> None:
        self._urls: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_peers(self, peers: list[dict]) -> None:
        with self._lock:
            self._urls = {p["id"]: p["url"] for p in peers
                          if isinstance(p, dict) and p.get("compatible", True)
                          and isinstance(p.get("id"), str) and isinstance(p.get("url"), str)}

    def url_of(self, origin_id: str) -> str | None:
        with self._lock:
            return self._urls.get(origin_id)

    def __call__(self, origin_id: str, path: str, params: dict) -> tuple[int, dict]:
        with self._lock:
            url = self._urls.get(origin_id)
        if url is None:
            raise OSError("unknown peer")
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not lan_guard.is_lan_address(host):
            raise OSError("peer is not on the home LAN")
        conn = HTTPConnection(host, parts.port or 80, timeout=TIMEOUT)
        try:
            conn.request("GET", f"{path}?{urlencode(params)}",
                         headers={"Host": f"{host}:{parts.port}",
                                  "Accept-Encoding": "gzip"})
            reply = conn.getresponse()
            raw = reply.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise OSError("response too large")
            if reply.getheader("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return reply.status, data if isinstance(data, dict) else {}
        except (ValueError, EOFError) as exc:
            raise OSError(str(exc)) from exc
        finally:
            conn.close()


class MeshLibrary:
    def __init__(self, indexer, *, store: replica_store.ReplicaStore | None = None,
                 fetcher: PeerFetcher | None = None,
                 busy: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.time) -> None:
        self.indexer = indexer
        self.store = store or replica_store.ReplicaStore()
        self.fetcher = fetcher or PeerFetcher()
        self.manager = replica_manager.ReplicaManager(
            self.store, self.fetcher, clock=clock, busy=busy)
        self.search_service = federated_search.FederatedSearch(
            self._local_rows, self._replica_rows, self._origins, self.fetcher)
        self.files = mesh_files.MeshFiles(indexer.resolve_path, self._peers_with, self.fetcher.url_of)
        self._poll_times: dict[str, float] = {}
        self._clock = clock
        self._lock = threading.Lock()

    # -- sources for federated search ------------------------------------
    def _local_rows(self, text: str, limit: int) -> list[dict]:
        with self.indexer._lock:
            rows, _p = search_engine.run(self.indexer._conn, text, limit)
        return rows

    def _replica_rows(self, text: str, limit: int) -> list[dict]:
        with self._lock:
            rows, _p = search_engine.run(self.store.conn, text, limit,
                                         source=search_engine.REPLICA)
        return rows

    def _origins(self) -> dict[str, dict]:
        with self._lock:
            return {o["origin_id"]: o for o in self.store.origins()}

    # -- browsing "Libraries on the network" ------------------------------
    def libraries(self) -> dict:
        shared = [f for f in self.indexer._folders if f.shared]
        with self.indexer._lock:
            counts = dict(self.indexer._conn.execute(
                "SELECT folder_id, COUNT(*) FROM entries GROUP BY folder_id").fetchall())
        origins = [{"id": "local", "name": "This computer", "online": True,
                    "folders": [{"label": f.label, "kind": f.kind, "count": counts.get(f.id, 0)}
                                for f in shared]}]
        with self._lock:
            for origin in self.store.origins():
                folders = library_browse.folder_summaries(
                    self.store.conn, "rentries", "origin_id = ?", [origin["origin_id"]], "folder_label")
                origins.append({"id": origin["origin_id"], "name": origin["name"] or "Another computer",
                                "online": origin["state"] in ("fresh", "stale"), "folders": folders})
        return {"origins": origins}

    def browse(self, origin: str, folder: str, path: str = "", cursor: str | None = None,
               limit: int = library_browse.PAGE) -> dict | None:
        """One level of a shared folder, or None if the origin/folder is unknown."""
        limit = max(1, min(int(limit), library_browse.PAGE))
        try:
            offset = int(base64.urlsafe_b64decode((cursor or "").encode()).decode()) if cursor else 0
        except (ValueError, UnicodeError):
            offset = 0
        if origin == "local":
            match = next((f for f in self.indexer._folders if f.shared and f.label == folder), None)
            if match is None:
                return None
            conn, lock = self.indexer._conn, self.indexer._lock
            table, scope, args = "entries", "folder_id = ?", [match.id]
            source = search_engine.LOCAL
            copies = [{"origin": "local", "origin_name": "This computer", "online": True}]
        else:
            info = self._origins().get(origin)
            if info is None:
                return None
            conn, lock = self.store.conn, self._lock
            table, scope, args = "rentries", "origin_id = ? AND folder_label = ?", [origin, folder]
            source = search_engine.REPLICA
            copies = [federated_search._copy(origin, info)]
        with lock:
            dirs, keys, more = library_browse.listing(conn, table, scope, args, path, offset, limit)
            rows = library_browse.rows_for(conn, source, scope, args, keys)
        items = [search_engine._item({**row, "copies": copies}) for row in rows]
        nxt = base64.urlsafe_b64encode(str(offset + limit).encode()).decode() if more else None
        return {"origin": origin, "folder": folder, "path": library_browse.clean_path(path).rstrip("/"),
                "dirs": dirs, "items": items, "next": nxt}

    @property
    def cache_dir(self) -> Path:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        return Path(base) / "smoothcast" / "house"

    def remote_sources(self, key: str) -> list[dict]:
        """Every online peer that holds ``key``, best first (for failover)."""
        found = []
        for origin in self._peers_with(key):
            url = self.fetcher.url_of(origin)
            if not url:
                continue
            with self._lock:
                row = self.store.conn.execute(
                    "SELECT title, rel_path FROM rentries WHERE origin_id=? AND content_key=?",
                    (origin, key)).fetchone()
                info = self.store.origin(origin) or {}
            if row:
                found.append({"origin": origin, "name": info.get("name", "") or "another computer",
                              "url": url, "title": row[0], "suffix": Path(row[1] or "").suffix})
        return found

    def remote_source(self, key: str) -> dict | None:
        sources = self.remote_sources(key)
        return sources[0] if sources else None

    def fetch_remote(self, key: str, source: dict, cancelled: Callable[[], bool] = lambda: False,
                     budget_gb: float = 20.0, keep: set[str] | None = None) -> Path:
        """Copy the file into the house cache (verified), trying other computers on failure."""
        candidates = [source] + [s for s in self.remote_sources(key) if s["origin"] != source["origin"]]
        failure: house_fetch.FetchError | None = None
        for candidate in candidates:
            try:
                path = house_fetch.fetch(candidate["url"], key, self.cache_dir,
                                         suffix=candidate["suffix"], cancelled=cancelled)
            except house_fetch.FetchError as exc:
                if cancelled():
                    raise
                failure = exc
                continue
            house_fetch.evict(self.cache_dir, int(budget_gb * 1024 ** 3),
                              keep={str(path), *(keep or set())})
            return path
        raise failure or house_fetch.FetchError("No computer has that file right now.")

    def _peers_with(self, key: str) -> list[str]:
        """Online peers whose replica holds this content key, best first."""
        with self._lock:
            rows = self.store.conn.execute(
                "SELECT r.origin_id FROM rentries r JOIN origins o ON o.origin_id=r.origin_id "
                "WHERE r.content_key=? AND o.state IN ('fresh','stale') "
                "ORDER BY o.last_seen_at DESC", (key,)).fetchall()
        return [r[0] for r in rows]

    # -- peers ------------------------------------------------------------
    def observe_peers(self, peers: list[dict]) -> None:
        """Called with the live peer snapshot (about once a second)."""
        self.fetcher.set_peers(peers)
        now = self._clock()
        for peer in peers:
            pid = peer.get("id")
            if not isinstance(pid, str) or not peer.get("compatible", True):
                continue
            with self._lock:
                self.store.touch_origin(pid, str(peer.get("name", "")), now)
                due = now - self._poll_times.get(pid, 0.0) >= 30.0
                if due:
                    self._poll_times[pid] = now
            if due:
                try:
                    status, gen = self.fetcher(pid, "/mesh/library/generation", {})
                except OSError:
                    continue
                if status == 200:
                    self.manager.on_peer_seen(pid, str(peer.get("name", "")), gen)

    # -- service ----------------------------------------------------------
    def start(self) -> None:
        self.manager.start()

    def stop(self) -> None:
        self.manager.stop()
        self.search_service.close()
        with self._lock:
            try:
                self.store.close()
            except Exception:
                pass
