"""#408: indexer v2 with changelog; #366 quick_hash; media name parsing."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fingerprint
import library_folders as lf
import library_index_v2 as li
import media_names


def make(tmp_path, clock=None, probe=None, busy=None):
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    folder = lf.LibraryFolder("f_1", str(lib), "Films")
    kwargs = {"probe": probe or (lambda p: {})}
    if clock:
        kwargs["clock"] = clock
    if busy:
        kwargs["busy"] = busy
    idx = li.LibraryIndexer(tmp_path / "db.sqlite3", **kwargs)
    idx.set_folders([folder])
    return idx, folder, lib


def test_add_modify_delete_produce_ordered_changelog(tmp_path):
    idx, folder, lib = make(tmp_path)
    (lib / "Paddington 2 (2017).mkv").write_bytes(b"a" * 100)
    (lib / "song.mp3").write_bytes(b"b" * 100)
    idx.scan_all()
    _origin, epoch, seq = idx.generation()
    changes = idx.changes_since(epoch, 0)
    assert [c["op"] for c in changes] == ["upsert", "upsert"] and seq == 2
    movie = next(c["entry"] for c in changes if c["entry"]["kind"] == "video")
    assert movie["title"] == "Paddington 2" and movie["year"] == 2017
    (lib / "song.mp3").write_bytes(b"c" * 120)     # modified -> new key
    (lib / "Paddington 2 (2017).mkv").unlink()      # deleted
    idx.scan_all()
    ops = [(c["op"]) for c in idx.changes_since(epoch, seq)]
    assert sorted(ops) == ["delete", "delete", "upsert"]
    assert idx.count() == 1


def test_unchanged_files_are_not_rehashed(tmp_path, monkeypatch):
    idx, _f, lib = make(tmp_path)
    (lib / "a.mkv").write_bytes(b"x" * 50)
    idx.scan_all()
    calls = []
    real = fingerprint.quick_hash
    monkeypatch.setattr(fingerprint, "quick_hash", lambda p: (calls.append(p), real(p))[1])
    result = idx.scan_all()
    assert calls == [] and result["skipped"] == 1


def test_stale_epoch_and_compacted_history_raise(tmp_path):
    idx, _f, lib = make(tmp_path)
    (lib / "a.mkv").write_bytes(b"x" * 50)
    idx.scan_all()
    with pytest.raises(li.StaleGeneration):
        idx.changes_since("wrong-epoch", 0)
    idx._set_meta("oldest_seq", "5")
    _o, epoch, _s = idx.generation()
    with pytest.raises(li.StaleGeneration):
        idx.changes_since(epoch, 2)


def test_missing_folder_deletes_only_after_24_hours(tmp_path):
    now = [1000.0]
    idx, folder, lib = make(tmp_path, clock=lambda: now[0])
    (lib / "a.mkv").write_bytes(b"x" * 50)
    idx.scan_all()
    os.rename(lib / "a.mkv", tmp_path / "a.mkv")
    lib.rmdir()
    idx.scan_all()
    assert idx.count() == 1                     # unplugged drive: keep entries
    now[0] += li.MISSING_GRACE_SECONDS + 1
    idx.scan_all()
    assert idx.count() == 0


def test_write_and_changelog_are_atomic(tmp_path):
    idx, folder, lib = make(tmp_path)
    (lib / "a.mkv").write_bytes(b"x" * 50)
    entry = li.build_entry(folder, "a.mkv", (lib / "a.mkv").stat(), "qh:test", {})

    class Failing:
        """Connection proxy whose entry insert fails after the changelog row."""
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if sql.lstrip().startswith("INSERT OR REPLACE INTO entries"):
                raise RuntimeError("disk full")
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    real = idx._conn
    idx._conn = Failing(real)
    with pytest.raises(RuntimeError):
        idx._upsert(entry, None)
    idx._conn = real
    idx._conn.commit()
    assert idx.generation()[2] == 0 and idx.count() == 0   # neither persisted


def test_busy_pauses_scanning_and_stop_is_prompt(tmp_path):
    gate = threading.Event()
    idx, _f, lib = make(tmp_path, busy=lambda: not gate.is_set())
    (lib / "a.mkv").write_bytes(b"x" * 50)
    idx.start()
    assert idx.count() == 0
    gate.set()
    for _ in range(100):
        if idx.count():
            break
        idx._stop.wait(0.1)
    idx.stop(5)
    assert idx.count() == 1 and not idx._thread.is_alive()


def test_snapshot_pages_cover_everything_once(tmp_path):
    idx, _f, lib = make(tmp_path)
    for i in range(7):
        (lib / f"t{i}.mp3").write_bytes(bytes([i]) * (30 + i))
    idx.scan_all()
    seen, cursor = [], None
    while True:
        items, cursor, _gen = idx.snapshot_page(cursor, limit=3)
        seen += [i["content_key"] for i in items]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 7


def test_quick_hash_identity(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"hello world")
    b.write_bytes(b"hello world")
    c.write_bytes(b"hello worle")
    assert fingerprint.quick_hash(a) == fingerprint.quick_hash(b) != fingerprint.quick_hash(c)
    big, big2 = tmp_path / "big", tmp_path / "big2"
    data = bytearray(os.urandom(13 * 1024 * 1024))
    big.write_bytes(bytes(data))
    data[len(data) // 2] ^= 0xFF                 # middle chunk differs
    big2.write_bytes(bytes(data))
    assert fingerprint.quick_hash(big) != fingerprint.quick_hash(big2)


@pytest.mark.parametrize("name,parent,expected", [
    ("Show.Name.S01E02.1080p.mkv", "", ("Show Name", 1, 2)),
    ("show 1x05.mkv", "", ("show", 1, 5)),
    ("The Office S03E10E11.mkv", "", ("The Office", 3, 10)),
    ("03 - The Fog.mkv", "Season 2", ("", 2, 3)),
    ("Episode 4.mp4", "Season 1", ("", 1, 4)),
    ("Paddington 2 (2017).mkv", "", None),
    ("Dancing Queen.mp3", "ABBA", None),
])
def test_parse_episode(name, parent, expected):
    assert media_names.parse_episode(name, parent) == expected


def test_parse_year_and_title():
    assert media_names.parse_year("Paddington 2 (2017).mkv") == 2017
    assert media_names.parse_year("2001 A Space Odyssey 1968.mkv") == 1968
    assert media_names.parse_year("noyear.mkv") is None
    assert media_names.clean_title("Movie.Name.2019.1080p.BluRay.x264.mkv") == "Movie Name"
