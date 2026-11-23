"""#366: content keys survive rename/move; hashing never blocks the caller's thread."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fingerprint
import watch_history

KEY_A = "qh:" + "a" * 32


def media(tmp_path, name="film.mkv", data=b"x" * 5000):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_get_never_hashes_on_the_callers_thread_then_serves_from_cache(tmp_path):
    threads = []

    def hasher(path):
        threads.append(threading.current_thread().name)
        return fingerprint.quick_hash(path)

    cache = fingerprint.KeyCache(hasher)
    path = media(tmp_path)
    assert cache.get(path) is None                         # first call: scheduled, not computed here
    cache.wait()
    key = cache.get(path)
    assert fingerprint.valid_key(key) == key == fingerprint.quick_hash(path)
    assert threads == [t for t in threads if t.startswith("content-key")] and len(threads) == 1
    assert cache.get(path) == key and len(threads) == 1    # cached: no second hash


def test_changed_or_missing_files_are_not_served_from_a_stale_cache(tmp_path):
    cache = fingerprint.KeyCache()
    path = media(tmp_path)
    cache.get(path)
    cache.wait()
    old = cache.get(path)
    path.write_bytes(b"y" * 7000)                          # replaced: new size
    assert cache.get(path) is None
    cache.wait()
    new = cache.get(path)
    assert new and new != old
    assert cache.get(tmp_path / "missing.mkv") is None


def test_cache_is_bounded_and_survives_hash_errors(tmp_path):
    def flaky(path):
        if "bad" in str(path):
            raise OSError("unreadable")
        return fingerprint.quick_hash(path)

    cache = fingerprint.KeyCache(flaky, limit=3)
    for i in range(6):
        cache.get(media(tmp_path, f"f{i}.mkv", bytes([i]) * 100))
    cache.get(media(tmp_path, "bad.mkv"))
    cache.wait()
    assert len(cache._cache) <= 3 and "bad" not in " ".join(cache._cache)
    assert cache.get(tmp_path / "bad.mkv") is None         # error means "no key yet", never an exception


def test_valid_key_rejects_garbage():
    assert fingerprint.valid_key(KEY_A) == KEY_A
    for bad in (None, 5, "", "qh:xyz", "qh:" + "A" * 32, "../../etc", "qh:" + "a" * 33):
        assert fingerprint.valid_key(bad) is None


def test_renamed_file_resumes_through_its_content_key():
    history = watch_history.record(None, "/films/Old/Alien.mkv", "stop", 1234.5, 100.0,
                                   duration=7000, fingerprint="10:20", content_key=KEY_A)
    moved = "/films/New/Alien (1979).mkv"
    cfg = {"watch_history": history}
    assert watch_history.saved_position(cfg, moved) is None           # path alone: lost
    assert watch_history.saved_position(cfg, moved, KEY_A) == 1234.5   # same content: found
    assert watch_history.saved_position(cfg, moved, "qh:" + "b" * 32) is None


def test_path_matches_without_a_key_still_respect_the_stat_fingerprint():
    history = watch_history.record(None, "/f/a.mkv", "stop", 50.0, 1.0, fingerprint="1:1")
    assert watch_history.latest_position(history, "/f/a.mkv", "1:1") == 50.0
    assert watch_history.latest_position(history, "/f/a.mkv", "9:9") is None   # file was replaced


def test_invalid_stored_keys_are_dropped_on_load_and_old_entries_still_load():
    entry = {"path": "/f/a.mkv", "event": "stop", "source": "cast", "position": 5.0, "at": 1.0,
             "content_key": "not-a-key"}
    assert watch_history.clean([entry])[0]["content_key"] is None
    legacy = {k: v for k, v in entry.items() if k != "content_key"}
    assert watch_history.clean([legacy])[0]["content_key"] is None
    good = watch_history.clean([{**entry, "content_key": KEY_A}])
    assert good[0]["content_key"] == KEY_A
