"""#411: replica store and manager - convergence, TTL states, recovery."""
from __future__ import annotations

from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_folders as lf
import library_index_v2 as li
import library_replication as lr
import replica_manager as rm
import replica_store as rs


class Origin:
    """A real indexer exposed through the replication builders (no HTTP)."""

    def __init__(self, tmp, name="o"):
        self.lib = tmp / name
        self.lib.mkdir()
        self.idx = li.LibraryIndexer(tmp / f"{name}.sqlite3", probe=lambda p: {})
        self.idx.set_folders([lf.LibraryFolder("f_1", str(self.lib), "Music", "music", True)])
        self.n = 0
        self.calls = []
        self.fail_after: int | None = None

    def add(self, count=1):
        for _ in range(count):
            self.n += 1
            (self.lib / f"t{self.n}.mp3").write_bytes(bytes([self.n % 250 + 1]) * (30 + self.n))
        self.idx.scan_all()

    def remove(self, rng):
        files = sorted(self.lib.glob("*.mp3"))
        if files:
            rng.choice(files).unlink()
            self.idx.scan_all()

    def shared_keys(self):
        return {e["content_key"] for e in self.idx.snapshot_page(None, 5000, shared_only=True)[0]}

    def fetch(self, origin_id, path, params):
        self.calls.append(path)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise OSError("network down")
        if path == "/mesh/library/changes":
            return lr.build_changes_response(self.idx, params["epoch"], params["since"], params.get("limit", 5000))
        return lr.build_snapshot_response(self.idx, params.get("cursor"), params.get("limit", 5000))


def manager(tmp, origin, now, **kw):
    store = rs.ReplicaStore(tmp / "replicas.sqlite3", clock=lambda: now[0])
    mgr = rm.ReplicaManager(store, origin.fetch, clock=lambda: now[0], **kw)
    return store, mgr


@pytest.mark.parametrize("seed", range(100))
def test_replica_converges_for_any_interleaving(tmp_path, seed):
    rng = random.Random(seed)
    origin = Origin(tmp_path)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "Study", None)
    origin.add(rng.randint(1, 4))
    for _ in range(rng.randint(3, 8)):
        action = rng.choice(["add", "remove", "sync", "sync", "restart", "dup"])
        if action == "add":
            origin.add(rng.randint(1, 3))
        elif action == "remove":
            origin.remove(rng)
        elif action == "sync":
            mgr.sync("o1")
        elif action == "restart":
            store.close()
            store, mgr = manager(tmp_path, origin, now)
        else:
            mgr.sync("o1")
            mgr.sync("o1")
    assert mgr.sync("o1")
    assert store.keys("o1") == origin.shared_keys(), f"seed {seed}"


def test_state_transitions_fresh_stale_offline_evicted(tmp_path):
    origin = Origin(tmp_path)
    origin.add(2)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "Study", {"epoch": "?", "seq": 0})
    mgr.tick()
    assert store.origin("o1")["state"] == "fresh" and len(store.keys("o1")) == 2
    now[0] += rm.OFFLINE_AFTER + 1
    mgr.tick()
    assert store.origin("o1")["state"] == "offline"
    mgr.on_peer_seen("o1", "Study")
    now[0] += rm.SOFT_TTL + 1
    mgr.on_peer_seen("o1", "Study")
    assert mgr.state_of(store.origin("o1"), now[0]) == "stale"
    now[0] += rm.HARD_TTL + 1
    mgr.tick()
    assert store.origin("o1") is None and store.keys("o1") == set()


def test_epoch_change_discards_replica_and_resnapshots(tmp_path):
    origin = Origin(tmp_path)
    origin.add(3)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "S")
    assert mgr.sync("o1") and len(store.keys("o1")) == 3
    origin.idx._set_meta("epoch", "new-epoch")           # origin reinstalled
    origin.n += 10
    origin.add(1)
    assert mgr.sync("o1")
    assert store.origin("o1")["epoch"] == "new-epoch" and store.keys("o1") == origin.shared_keys()


def test_crash_mid_snapshot_resumes_from_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "PAGE", 3)
    origin = Origin(tmp_path)
    origin.add(8)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "S")
    origin.fail_after = 1                                # one page then the network dies
    assert not mgr.sync("o1")
    row = store.origin("o1")
    assert row["snapshot_active"] == 1 and row["snapshot_cursor"]
    origin.fail_after = None
    origin.calls.clear()
    store.close()
    store, mgr = manager(tmp_path, origin, now)
    now[0] += 3600                                       # past the failure backoff
    assert mgr.sync("o1")
    assert origin.calls[0] == "/mesh/library/snapshot"   # resumed, not restarted from changes
    assert store.keys("o1") == origin.shared_keys()


def test_corrupt_database_recovers_and_resyncs(tmp_path):
    origin = Origin(tmp_path)
    origin.add(2)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "S")
    mgr.sync("o1")
    store.close()
    (tmp_path / "replicas.sqlite3").write_bytes(b"not a database" * 100)
    store, mgr = manager(tmp_path, origin, now)
    assert store.recovered and list(tmp_path.glob("replicas.sqlite3.corrupt-*"))
    mgr.on_peer_seen("o1", "S")
    assert mgr.sync("o1") and store.keys("o1") == origin.shared_keys()


def test_malformed_page_is_discarded_with_backoff(tmp_path):
    origin = Origin(tmp_path)
    origin.add(2)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "S")
    real = origin.fetch

    def bad(origin_id, path, params):
        status, body = real(origin_id, path, params)
        if path == "/mesh/library/snapshot":
            body["entries"][0]["title"] = "x" * 900       # oversized string
        return status, body

    mgr.fetch = bad
    assert not mgr.sync("o1")
    assert store.keys("o1") == set()
    row = store.origin("o1")
    assert row["fail_count"] == 1 and row["backoff_until"] == now[0] + 60
    mgr.tick()                                           # inside backoff: no new attempt
    assert store.origin("o1")["fail_count"] == 1


def test_busy_defers_sync_entirely(tmp_path):
    origin = Origin(tmp_path)
    origin.add(2)
    now = [1000.0]
    busy = [True]
    store, mgr = manager(tmp_path, origin, now, busy=lambda: busy[0])
    mgr.on_peer_seen("o1", "S")
    assert not mgr.sync("o1") and origin.calls == []     # transcoding: nothing fetched
    busy[0] = False
    assert mgr.sync("o1") and store.keys("o1") == origin.shared_keys()


def test_large_pages_are_throttled_to_the_bandwidth_cap(tmp_path):
    slept = []
    store = rs.ReplicaStore(tmp_path / "r.sqlite3")
    big = {"epoch": "e", "at_seq": 0, "next": None,
           "entries": [{"content_key": f"qh:{i}", "kind": "music", "title": "t" * 400}
                       for i in range(400)]}               # ~170 KB of JSON
    mgr = rm.ReplicaManager(store, lambda *_: (200, big), sleep=slept.append, bandwidth=100_000)
    mgr.on_peer_seen("o1", "S")
    mgr.store.conn.execute("UPDATE origins SET epoch=NULL")
    assert mgr._get("o1", "/mesh/library/snapshot", {})[0] == 200
    assert len(slept) == 1 and 1.0 < slept[0] < 3.0       # size / 100 KB/s


def test_unshared_folder_disappears_from_replica(tmp_path):
    origin = Origin(tmp_path)
    origin.add(3)
    now = [1000.0]
    store, mgr = manager(tmp_path, origin, now)
    mgr.on_peer_seen("o1", "S")
    mgr.sync("o1")
    folder = origin.idx._folders[0]
    origin.idx.set_folders([lf.LibraryFolder(folder.id, folder.path, folder.label, folder.kind, False)])
    assert mgr.sync("o1") and store.keys("o1") == set()


def test_origin_cap_evicts_least_recently_seen(tmp_path):
    store = rs.ReplicaStore(tmp_path / "r.sqlite3")
    for i in range(rs.MAX_ORIGINS + 3):
        store.touch_origin(f"o{i}", f"N{i}", float(i))
    ids = {o["origin_id"] for o in store.origins()}
    assert len(ids) == rs.MAX_ORIGINS and "o0" not in ids and f"o{rs.MAX_ORIGINS + 2}" in ids
