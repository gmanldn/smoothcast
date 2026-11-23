"""Performance and size gates for house search (#415, budgets from docs/MESH_SEARCH.md).

Opt-in: ``SMOOTHCAST_PERF=1 pytest tests/perf -s``. CI runs them serially in
the ``search-performance`` job of the MINOR/MAJOR full lane (never under
``-n auto``, where workers would contend and each rebuild the fixture).
Budgets are multiplied by ``SMOOTHCAST_PERF_SLACK`` (default 1, 3 in CI). Each
query is run several times and the *worst* run must meet the budget.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".." / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import federated_search
import library_folders as lf
import library_index_v2 as li
import library_replication as lr
import replica_store as rs
import search_engine as se
from perf import synthetic_library as sl

ENABLED = bool(os.environ.get("SMOOTHCAST_PERF"))
pytestmark = [pytest.mark.perf, pytest.mark.skipif(
    not ENABLED, reason="performance gates run with SMOOTHCAST_PERF=1")]
SLACK = float(os.environ.get("SMOOTHCAST_PERF_SLACK") or 1.0)
LIBRARY = 100_000
RUNS = 7

QUERY_BUDGET_MS = 30        # docs/MESH_SEARCH.md: local + replica query
BROAD_FILTER_BUDGET_MS = 60  # filter-only scans over a 200k-entry replica store
TEXT_QUERIES = ["night", "paddin", "dark river", "kind:music artist:abba",
                'artist:"miles davis" night', "year:1990s kind:music", "padingtn"]
BROAD_QUERIES = ["kind:film year:1980s"]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("perf")
    indexer = li.LibraryIndexer(tmp / "local.sqlite3", probe=lambda p: {})
    indexer.set_folders([lf.LibraryFolder("f_1", str(tmp), "Lib", "auto", True)])
    sl.fill_local(indexer._conn, LIBRARY, seed=1)
    store = rs.ReplicaStore(tmp / "replicas.sqlite3")
    sl.fill_replica(store.conn, "a", LIBRARY, seed=2)
    sl.fill_replica(store.conn, "b", LIBRARY, seed=3)
    for conn in (indexer._conn, store.conn):
        conn.execute("ANALYZE")
    return indexer, store


def worst_ms(fn) -> float:
    worst = 0.0
    for _ in range(RUNS):
        start = time.perf_counter()
        fn()
        worst = max(worst, (time.perf_counter() - start) * 1000)
    return worst


@pytest.mark.parametrize("query", TEXT_QUERIES)
def test_local_and_replica_queries_meet_the_budget(world, query):
    indexer, store = world
    local = worst_ms(lambda: se.run(indexer._conn, query, 50, 0, deadline=5))
    replica = worst_ms(lambda: se.run(store.conn, query, 50, 0, source=se.REPLICA, deadline=5))
    print(f"\n[perf] {query!r}: local {local:.1f} ms, 200k replicas {replica:.1f} ms")
    assert local <= QUERY_BUDGET_MS * SLACK and replica <= QUERY_BUDGET_MS * SLACK


@pytest.mark.parametrize("query", BROAD_QUERIES)
def test_broad_filter_scans_stay_interactive(world, query):
    indexer, store = world
    local = worst_ms(lambda: se.run(indexer._conn, query, 50, 0, deadline=5))
    replica = worst_ms(lambda: se.run(store.conn, query, 50, 0, source=se.REPLICA, deadline=5))
    print(f"\n[perf] broad {query!r}: local {local:.1f} ms, 200k replicas {replica:.1f} ms")
    assert max(local, replica) <= BROAD_FILTER_BUDGET_MS * SLACK


def test_no_match_is_effectively_free(world):
    indexer, _store = world
    assert worst_ms(lambda: se.run(indexer._conn, "xyzzyq", 50, 0)) <= 5 * SLACK


def test_federated_cached_path_over_three_origins(world):
    indexer, store = world
    origins = {o["origin_id"]: {**o, "state": "fresh", "last_synced_at": 1.0}
               for o in [{"origin_id": "a", "name": "A", "last_seen_at": 1.0},
                         {"origin_id": "b", "name": "B", "last_seen_at": 1.0}]}
    service = federated_search.FederatedSearch(
        lambda t, n: se.run(indexer._conn, t, n)[0],
        lambda t, n: se.run(store.conn, t, n, source=se.REPLICA)[0],
        lambda: origins, lambda *a: (200, {"entries": []}))
    ms = worst_ms(lambda: service.search("night", 50))
    print(f"\n[perf] federated cached search: {ms:.1f} ms")
    assert ms <= 2 * QUERY_BUDGET_MS * SLACK            # two index queries + merge


def test_snapshot_of_100k_entries_is_fast_and_small(world):
    indexer, _store = world
    start = time.perf_counter()
    cursor, entries, compressed = None, 0, 0
    while True:
        status, page = lr.build_snapshot_response(indexer, cursor, lr.MAX_PAGE)
        assert status == 200
        entries += len(page["entries"])
        compressed += len(gzip.compress(json.dumps(page, separators=(",", ":")).encode(), 5))
        cursor = page["next"]
        if cursor is None:
            break
    seconds = time.perf_counter() - start
    print(f"\n[perf] snapshot: {entries} entries, {compressed / 1e6:.1f} MB gzip, {seconds:.1f} s")
    assert entries == LIBRARY
    assert compressed <= 15 * 1024 * 1024                # transfer size budget, no slack
    assert seconds <= 10 * SLACK
