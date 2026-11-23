"""Persistent mesh metadata cache (#401)."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_cache as mc
import mesh_model as mm
import mesh_state as st

ME = "1" * 32
NOW = 1_800_000_000.0


class Wall:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


def rec(node, name="Peer", targets=(), **kw):
    return mm.NodeRecord(node_id=node * 32, boot_id="c" * 32, name=name, version="1.2.0",
                         capabilities=("room",), targets=tuple(targets), **kw)


def view(*records):
    return st.MeshView(1, ME, (rec("1"),) + tuple(records))


def tgt(i, state="ready", name=None):
    return mm.TargetObservation(f"tv-{i:04d}", "cast", name or f"TV {i}", state=state,
                                model="Chromecast", formats=("video/mp4",))


@pytest.fixture
def cache(tmp_path):
    wall = Wall()
    c = mc.MeshCache(tmp_path / "mesh" / "cache.sqlite", wall=wall).open()
    c.wall = wall
    yield c
    c.close()


def test_peers_and_targets_round_trip_as_cached(cache):
    cache.record_view(view(rec("a", "Study PC", targets=[tgt(1)]), rec("b", "Laptop")))
    loaded = cache.load()
    assert [p.name for p in loaded.peers] == ["Laptop", "Study PC"] or {p.name for p in loaded.peers} == {"Study PC", "Laptop"}
    assert all(p.cached for p in loaded.peers) and ME not in {p.node_id for p in loaded.peers}
    (target,) = loaded.targets
    assert target.name == "TV 1" and target.formats == ("video/mp4",) and target.cached
    assert target.reliability is None                     # too few samples yet


def test_warm_start_after_reopen_and_placeholder_records(tmp_path):
    path = tmp_path / "c.sqlite"
    first = mc.MeshCache(path).open()
    first.record_view(view(rec("a", "Study PC")))
    first.set_last_primary("a" * 32)
    first.close()
    second = mc.MeshCache(path).open()
    loaded = second.load()
    assert loaded.last_primary == "a" * 32
    placeholders = mc.cached_records(loaded, live_ids={"b" * 32})
    assert [r.name for r in placeholders] == ["Study PC"]
    assert mc.cached_records(loaded, live_ids={"a" * 32}) == []
    second.set_last_primary("short")                        # ignored
    assert second.load().last_primary == "a" * 32
    second.close()


def test_reliability_and_edge_history_accumulate(cache):
    for _ in range(4):
        cache.record_view(view(rec("a", targets=[tgt(1, "ready")])))
    cache.record_view(view(rec("a", targets=[tgt(1, "unreachable")])))
    assert cache.reliability("tv-0001") == pytest.approx(0.8)
    ratio, rtt = cache.edge_stats("a" * 32, "tv-0001")
    assert ratio == pytest.approx(0.8) and rtt is None
    assert cache.reliability("nope") is None and cache.edge_stats("x", "y") == (None, None)


def test_rtt_from_edges_is_kept(cache):
    record = rec("a", targets=[tgt(1)], edges=(mm.EdgeObservation("target", "tv-0001", 0, 12),))
    cache.record_view(view(record))
    assert cache.edge_stats("a" * 32, "tv-0001")[1] == 12


def test_ttl_expiry_on_open_and_prune(tmp_path):
    wall = Wall()
    c = mc.MeshCache(tmp_path / "c.sqlite", wall=wall).open()
    c.record_view(view(rec("a", targets=[tgt(1)])))
    wall.t += mc.PEER_TTL_S + 10
    c.record_view(view(rec("b", targets=[tgt(2)])))
    c._prune_locked()
    loaded = c.load()
    assert {p.name for p in loaded.peers} == {"Peer"} and len(loaded.peers) == 1
    assert {t.target_id for t in loaded.targets} == {"tv-0001", "tv-0002"}   # 30-day target TTL
    wall.t += mc.TARGET_TTL_S + 1
    c._prune_locked()
    assert c.counts() == {"peers": 0, "targets": 0, "edges": 0}
    c.close()


def test_lru_caps_evict_the_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "MAX_PEERS", 5)
    monkeypatch.setattr(mc, "MAX_TARGETS", 4)
    wall = Wall()
    c = mc.MeshCache(tmp_path / "c.sqlite", wall=wall).open()
    for index in range(10):
        wall.t += 1
        c.record_view(view(rec(f"{index:x}", f"P{index}", targets=[tgt(index)])))
    counts = c.counts()
    assert counts["peers"] == 5 and counts["targets"] == 4
    assert {p.name for p in c.load().peers} == {f"P{i}" for i in range(5, 10)}
    c.close()


def test_a_500_peer_fixture_loads_fast(tmp_path):
    c = mc.MeshCache(tmp_path / "c.sqlite").open()
    recs = [rec(f"{i:032x}"[0], f"P{i}") for i in range(1)]
    db = c._conn()
    now = int(time.time())
    db.executemany("INSERT INTO peers VALUES(?,?,?,?,?,?)",
                   [(f"{i:032x}", f"P{i}", "1.2.0", "room", now, now - i) for i in range(500)])
    db.commit()
    started = time.perf_counter()
    loaded = c.load()
    assert len(loaded.peers) == 500 and time.perf_counter() - started < 0.1
    assert recs
    c.close()


def test_secrets_names_addresses_and_paths_are_never_written(tmp_path):
    path = tmp_path / "c.sqlite"
    c = mc.MeshCache(path).open()
    secret = rec(
        "a", "Study PC", addresses=("10.77.66.55",),
        clients=(mm.ClientSummary("cl1", "screen", name="Sam-secret-phone"),),
        sources=(mm.SourceSummary("audio", 9, ("audio/secret-fmt",)),),
        targets=[tgt(1)])
    c.record_view(view(secret))
    c.close()
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("c.sqlite*"))
    for needle in (b"10.77.66.55", b"Sam-secret-phone", b"audio/secret-fmt", b"cl1"):
        assert needle not in blob
    assert b"Study PC" in blob


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_files_are_private(tmp_path):
    c = mc.MeshCache(tmp_path / "d" / "c.sqlite").open()
    c.record_view(view(rec("a")))
    assert (tmp_path / "d").stat().st_mode & 0o777 == 0o700
    for f in (tmp_path / "d").glob("c.sqlite*"):
        assert f.stat().st_mode & 0o077 == 0, f
    c.close()


def test_corruption_is_quarantined_and_a_fresh_cache_starts(tmp_path):
    path = tmp_path / "c.sqlite"
    path.write_bytes(b"this is definitely not sqlite" * 100)
    c = mc.MeshCache(path).open()
    assert c.recovered and c.counts()["peers"] == 0
    assert list(tmp_path.glob("c.sqlite.corrupt-*"))
    c.record_view(view(rec("a")))
    assert c.counts()["peers"] == 1
    c.close()


def test_quarantine_files_are_bounded(tmp_path):
    for stamp in range(5):
        (tmp_path / f"c.sqlite.corrupt-{stamp}").write_bytes(b"x")
    (tmp_path / "c.sqlite").write_bytes(b"garbage" * 50)
    mc.MeshCache(tmp_path / "c.sqlite").open().close()
    assert len(list(tmp_path.glob("c.sqlite.corrupt-*"))) <= mc.MAX_QUARANTINED


def test_a_cache_from_a_newer_version_is_set_aside(tmp_path):
    path = tmp_path / "c.sqlite"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version={mc.SCHEMA_VERSION + 5}")
    db.execute("CREATE TABLE x(a)")
    db.commit()
    db.close()
    c = mc.MeshCache(path).open()
    assert c.recovered
    c.close()


def test_forget_network_removes_everything_and_cache_is_reusable(tmp_path):
    path = tmp_path / "c.sqlite"
    c = mc.MeshCache(path).open()
    c.record_view(view(rec("a", targets=[tgt(1)])))
    (tmp_path / "c.sqlite.corrupt-1").write_bytes(b"x")
    c.forget()
    assert not list(tmp_path.glob("c.sqlite*"))
    with pytest.raises(RuntimeError):
        c.counts()
    c.open()
    assert c.counts() == {"peers": 0, "targets": 0, "edges": 0}
    c.close()


def test_concurrent_writer_and_reader_threads_do_not_conflict(tmp_path):
    c = mc.MeshCache(tmp_path / "c.sqlite").open()
    errors = []

    def writer():
        try:
            for i in range(60):
                c.record_view(view(rec(f"{i % 15:x}", targets=[tgt(i % 20)])))
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(60):
                c.load()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors
    c.close()
    c.close()


def test_known_target_ids(cache):
    cache.record_view(view(rec("a", targets=[tgt(1), tgt(2)])))
    assert cache.known_target_ids() == {"tv-0001", "tv-0002"}
