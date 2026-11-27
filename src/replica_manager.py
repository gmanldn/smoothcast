"""Keeps peers' library replicas current, with TTLs (issue #411).

Pure scheduling/sync logic with injected ``fetch``, clock, sleeper and ``busy``
so it is deterministic in tests. See docs/MESH_SEARCH.md sections 2-3.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable

import library_replication
import task_runtime
import replica_store

SOFT_TTL = 10 * 60.0
OFFLINE_AFTER = 30.0
HARD_TTL = 7 * 24 * 3600.0
MAX_SNAPSHOTS = 2
BANDWIDTH = 2 * 1024 * 1024  # bytes per second
PAGE = 5000

Fetch = Callable[[str, str, dict], "tuple[int, dict]"]


class ReplicaManager:
    def __init__(self, store: replica_store.ReplicaStore, fetch: Fetch, *,
                 clock: Callable[[], float] = time.time,
                 busy: Callable[[], bool] = lambda: False,
                 sleep: Callable[[float], None] = time.sleep,
                 bandwidth: float = BANDWIDTH) -> None:
        self.store, self.fetch, self.clock = store, fetch, clock
        self.busy, self.sleep, self.bandwidth = busy, sleep, bandwidth
        self._advertised: dict[str, dict] = {}
        self._syncing: set[str] = set()
        self._snapshots = 0
        self._lock = threading.RLock()
        self._scope: task_runtime.Scope | None = None
        self._thread: threading.Thread | None = None

    # -- observations -----------------------------------------------------
    def on_peer_seen(self, origin_id: str, name: str, generation: dict | None = None) -> None:
        now = self.clock()
        with self._lock:
            self.store.touch_origin(origin_id, name, now)
            if generation:
                self._advertised[origin_id] = generation

    def state_of(self, origin: dict, now: float) -> str:
        unseen = now - origin["last_seen_at"]
        if unseen > HARD_TTL:
            return "evicting"
        if unseen > OFFLINE_AFTER:
            return "offline"
        synced = origin.get("last_synced_at")
        if synced is None or now - synced > SOFT_TTL or self._behind(origin):
            return "stale"
        return "fresh"

    def _behind(self, origin: dict) -> bool:
        gen = self._advertised.get(origin["origin_id"])
        if not gen:
            return False
        return gen.get("epoch") != origin.get("epoch") or gen.get("seq", 0) != origin.get("seq", 0)

    # -- scheduling -------------------------------------------------------
    def tick(self) -> list[str]:
        """Update states, evict the unseen, sync what is due; returns synced ids."""
        now = self.clock()
        synced = []
        with self._lock:
            for origin in self.store.origins():
                state = self.state_of(origin, now)
                if state == "evicting":
                    self.store.delete_origin(origin["origin_id"])
                    self._advertised.pop(origin["origin_id"], None)
                    continue
                if state != origin["state"]:
                    self.store.set_state(origin["origin_id"], state)
                if state == "stale" and now >= origin["backoff_until"]:
                    if self.sync(origin["origin_id"]):
                        synced.append(origin["origin_id"])
            while self.store.db_bytes() > replica_store.MAX_DB_BYTES:
                if self.store.evict_least_recently_seen() is None:
                    break
        return synced

    # -- syncing ----------------------------------------------------------
    def sync(self, origin_id: str) -> bool:
        """Bring one replica up to date. False when deferred or failed."""
        with self._lock:
            if origin_id in self._syncing or self.busy():
                return False
            self._syncing.add(origin_id)
        try:
            return self._sync(origin_id)
        except (OSError, ValueError, KeyError, TypeError):
            self.store.record_failure(origin_id, self.clock())
            return False
        finally:
            with self._lock:
                self._syncing.discard(origin_id)

    def _get(self, origin_id: str, path: str, params: dict) -> tuple[int, dict]:
        status, payload = self.fetch(origin_id, path, params)
        size = len(json.dumps(payload, separators=(",", ":")))
        if self.bandwidth and size > 64 * 1024:
            self.sleep(size / self.bandwidth)
        return status, payload

    def _sync(self, origin_id: str) -> bool:
        row = self.store.origin(origin_id)
        if row is None:
            return False
        if row["snapshot_active"] or not row["epoch"]:
            if not self._snapshot(origin_id):
                return False
            row = self.store.origin(origin_id) or row
        while True:
            status, body = self._get(origin_id, "/mesh/library/changes",
                                     {"epoch": row["epoch"], "since": row["seq"], "limit": PAGE})
            if status == 410:
                self.store.reset_origin(origin_id)
                if not self._snapshot(origin_id):
                    return False
                row = self.store.origin(origin_id) or row
                continue
            if status != 200 or not self._valid_changes(body):
                self.store.record_failure(origin_id, self.clock())
                return False
            self.store.apply_changes(origin_id, body["epoch"], body["changes"], body["to"],
                                     self.clock())
            row = self.store.origin(origin_id) or row
            if not body["more"]:
                return True
            if self.busy():
                return False

    def _snapshot(self, origin_id: str) -> bool:
        with self._lock:
            if self._snapshots >= MAX_SNAPSHOTS:
                return False
            self._snapshots += 1
        try:
            while True:
                row = self.store.origin(origin_id) or {}
                cursor = row.get("snapshot_cursor") if row.get("snapshot_active") else None
                params = {"limit": PAGE, **({"cursor": cursor} if cursor else {})}
                status, body = self._get(origin_id, "/mesh/library/snapshot", params)
                if status != 200 or not self._valid_snapshot(body):
                    self.store.record_failure(origin_id, self.clock())
                    return False
                self.store.apply_snapshot_page(origin_id, body["epoch"], body["entries"],
                                               body["next"], body["at_seq"], self.clock())
                if body["next"] is None:
                    return True
                if self.busy():
                    return False
        finally:
            with self._lock:
                self._snapshots -= 1

    @staticmethod
    def _valid_changes(body: object) -> bool:
        if not isinstance(body, dict) or not isinstance(body.get("changes"), list):
            return False
        if not isinstance(body.get("epoch"), str) or not isinstance(body.get("to"), int):
            return False
        for change in body["changes"]:
            if not isinstance(change, dict):
                return False
            if change.get("op") == "upsert":
                if not library_replication.validate_entry(change.get("entry")):
                    return False
            elif change.get("op") != "delete" or not isinstance(change.get("content_key"), str):
                return False
        return True

    @staticmethod
    def _valid_snapshot(body: object) -> bool:
        return (isinstance(body, dict) and isinstance(body.get("epoch"), str)
                and isinstance(body.get("at_seq"), int) and isinstance(body.get("entries"), list)
                and all(library_replication.validate_entry(e) for e in body["entries"]))

    # -- service ----------------------------------------------------------
    def start(self, interval: float = 10.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        runtime = task_runtime.shared()
        self._scope = runtime.scope()

        def run(scope: task_runtime.Scope) -> None:
            while not scope.wait(interval):
                try:
                    self.tick()
                except Exception:
                    pass
        self._thread = runtime.spawn_daemon("replica-manager", self._scope, run)

    def stop(self, timeout: float = 5.0) -> None:
        if self._scope:
            self._scope.cancel()
        if self._thread:
            self._thread.join(timeout)
