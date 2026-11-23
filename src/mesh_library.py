"""Glue for house-wide library search (issues #411, #412).

``PeerFetcher`` talks to peers' ``/mesh/library/*`` routes over plain HTTP on
the trusted LAN; ``MeshLibrary`` keeps replicas current from live peer
discovery and exposes federated search to the portal.
"""
from __future__ import annotations

import gzip
from http.client import HTTPConnection
import json
import threading
import time
from typing import Callable
from urllib.parse import urlencode, urlsplit

import federated_search
import lan_guard
import mesh_files
import replica_manager
import replica_store
import search_engine

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
