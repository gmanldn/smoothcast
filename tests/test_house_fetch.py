"""#414/#424: verified, resumable copy of another computer's media; queue integration."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fingerprint
import house_fetch as hf
import library_folders as lf
import library_index_v2 as li
import mesh_files
import portal
from cast_portal_queue import PortalQueueMixin
from test_room_conformance import RoomHarness

DATA = os.urandom(2_300_000)


@pytest.fixture
def origin(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "Film (1999).mkv").write_bytes(DATA)
    idx = li.LibraryIndexer(tmp_path / "o.sqlite3", probe=lambda p: {})
    idx.set_folders([lf.LibraryFolder("f_1", str(lib), "Films", "video", True)])
    idx.scan_all()
    key = idx.snapshot_page(None)[0][0]["content_key"]
    harness = RoomHarness(count=1)
    harness.server.mesh_files = mesh_files.MeshFiles(idx.resolve_path, lambda k: [], lambda o: None)
    url = f"http://127.0.0.1:{harness.server.server_address[1]}/"
    yield url, key, tmp_path / "cache"
    harness.close()


def test_fetch_copies_verifies_and_reuses_the_cache(origin):
    url, key, cache = origin
    seen = []
    path = hf.fetch(url, key, cache, suffix=".mkv", progress=lambda a, b: seen.append((a, b)), min_free=0)
    assert path.read_bytes() == DATA and path.name == key[3:] + ".mkv"
    assert seen[-1] == (len(DATA), len(DATA)) and not list(cache.glob("*.part"))
    mtime = path.stat().st_mtime
    again = hf.fetch("http://127.0.0.1:9/", key, cache, suffix=".mkv", min_free=0)   # no network needed
    assert again == path and path.stat().st_mtime >= mtime


def test_fetch_resumes_from_a_partial_file(origin):
    url, key, cache = origin
    cache.mkdir()
    part = hf.cache_path(cache, key, ".mkv").with_suffix(".mkv.part")
    part.write_bytes(DATA[:1_000_000])
    path = hf.fetch(url, key, cache, suffix=".mkv", min_free=0)
    assert path.read_bytes() == DATA and not part.exists()


def test_stale_oversized_partial_is_restarted(origin):
    url, key, cache = origin
    cache.mkdir()
    hf.cache_path(cache, key, ".mkv").with_suffix(".mkv.part").write_bytes(DATA + b"junk")
    assert hf.fetch(url, key, cache, suffix=".mkv", min_free=0).read_bytes() == DATA


def test_content_that_does_not_match_its_key_is_refused_and_removed(origin):
    url, key, cache = origin
    wrong = "qh:" + "0" * 32
    with pytest.raises(hf.FetchError):
        hf.fetch(url, wrong, cache, suffix=".mkv", min_free=0)       # origin has no such key -> 404
    assert not list(cache.glob("*")) or all(p.suffix != ".mkv" for p in cache.glob("*"))


def test_hash_mismatch_deletes_the_download(origin, monkeypatch):
    url, key, cache = origin
    monkeypatch.setattr(fingerprint, "quick_hash", lambda p: "qh:" + "f" * 32)
    with pytest.raises(hf.FetchError, match="changed"):
        hf.fetch(url, key, cache, suffix=".mkv", min_free=0)
    assert list(cache.glob("*")) == []


def test_guards_disk_space_lan_only_cancel_and_bad_keys(origin, tmp_path):
    url, key, cache = origin
    with pytest.raises(hf.FetchError, match="disk space"):
        hf.fetch(url, key, cache, suffix=".mkv", min_free=10 ** 15)
    with pytest.raises(hf.FetchError, match="home network"):
        hf.fetch("http://8.8.8.8/", key, cache, suffix=".mkv")
    with pytest.raises(hf.FetchError, match="Cancelled"):
        hf.fetch(url, key, cache, suffix=".mkv", cancelled=lambda: True, min_free=0)
    with pytest.raises(hf.FetchError):
        hf.cache_path(cache, "../../etc/passwd", ".mkv")
    assert hf.cache_path(cache, key, "../evil").suffix == ".bin"      # unsafe suffix neutralised
    assert hf.cache_path(cache, key, ".MKV").name.endswith(".mkv")


class Flaky(BaseHTTPRequestHandler):
    drops = 1
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        header = self.headers.get("Range", "")
        start = int(header[6:].split("-")[0]) if header.startswith("bytes=") else 0
        body = DATA[start:]
        self.send_response(206 if header else 200)
        self.send_header("Content-Length", str(len(body)))
        if header:
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        self.end_headers()
        if Flaky.drops > 0 and start == 0:
            Flaky.drops -= 1
            self.wfile.write(body[:900_000])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


def test_an_interrupted_transfer_resumes_and_still_verifies(tmp_path):
    key = None
    path = tmp_path / "x.bin"
    path.write_bytes(DATA)
    key = fingerprint.quick_hash(path)
    Flaky.drops = 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = hf.fetch(f"http://127.0.0.1:{server.server_address[1]}/", key, tmp_path / "c",
                       suffix=".mkv", min_free=0)
        assert out.read_bytes() == DATA and Flaky.drops == 0
    finally:
        server.shutdown()
        server.server_close()


def test_evict_removes_least_recently_used_but_never_kept_or_partial(tmp_path):
    for i, name in enumerate(("old.mkv", "mid.mkv", "new.mkv", "busy.mkv", "x.mkv.part")):
        f = tmp_path / name
        f.write_bytes(b"x" * 100)
        os.utime(f, (1000 + i, 1000 + i))
    removed = hf.evict(tmp_path, 250, keep={str(tmp_path / "old.mkv")})
    assert removed == ["mid.mkv", "new.mkv"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["busy.mkv", "old.mkv", "x.mkv.part"]


# --- queue integration -----------------------------------------------------
class FakeMesh:
    def __init__(self, source):
        self.source, self.fetched = source, []

    def remote_source(self, key):
        return self.source

    def fetch_remote(self, key, source, cancelled=lambda: False, keep=None):
        self.fetched.append(key)
        if source.get("fail"):
            raise hf.FetchError("The other computer no longer has that file.")
        return Path("/cache") / "film.mkv"


class QueueHost(PortalQueueMixin):
    def __init__(self, source):
        self.queue, self.queue_durations, self.busy, self._closing = [], {}, False, False
        self._mesh_library = FakeMesh(source)
        self.enqueued, self.toasts = [], []
        self.deferred = []

    def _enqueue(self, paths):
        self.enqueued += paths

    def toast(self, text, error=False):
        self.toasts.append((text, error))

    def _portal_run_async(self, work, done, failed):
        self.deferred.append((work, done, failed))

    def finish(self):
        work, done, failed = self.deferred.pop(0)
        try:
            result = work()
        except Exception as exc:
            failed(exc)
        else:
            done(result)


KEY = "qh:" + "a" * 32
SOURCE = {"origin": "p", "name": "Study PC", "url": "http://192.168.1.9:80/", "title": "Alien", "suffix": ".mkv"}


def test_remote_result_is_copied_then_queued_with_its_title():
    host = QueueHost(SOURCE)
    message = host._portal_queue_action("queue_add_key", {"key": KEY})
    assert "Copying “Alien” from Study PC" in message and host.enqueued == []
    assert host._portal_queue_action("queue_add_key", {"key": KEY}).startswith("Already fetching")
    host.finish()
    assert host.enqueued == ["/cache/film.mkv"]
    assert host._portal_queue_display_names["/cache/film.mkv"] == "Alien"
    assert KEY not in host._portal_fetching


def test_failed_copy_toasts_a_clear_message_and_allows_retry():
    host = QueueHost({**SOURCE, "fail": True})
    host._portal_queue_action("queue_add_key", {"key": KEY})
    host.finish()
    assert host.enqueued == []
    text, error = host.toasts[-1]
    assert error and "Couldn't copy “Alien”" in text and "no longer has that file" in text
    assert host._portal_queue_action("queue_add_key", {"key": KEY}).startswith("Copying")


def test_no_online_copy_anywhere_is_a_clear_404():
    host = QueueHost(None)
    with pytest.raises(portal.PortalRequestError) as err:
        host._portal_queue_action("queue_add_key", {"key": KEY})
    assert err.value.status == 404 and "asleep" in err.value.message


def test_fetch_remote_fails_over_to_the_next_computer_and_trims_the_cache(origin, tmp_path, monkeypatch):
    import mesh_library
    import replica_store as rs
    url, key, _cache = origin
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    local = li.LibraryIndexer(tmp_path / "local.sqlite3", probe=lambda p: {})
    store = rs.ReplicaStore(tmp_path / "r.sqlite3")
    mesh = mesh_library.MeshLibrary(local, store=store)
    for oid, name in (("dead", "Dead PC"), ("live", "Study PC")):
        store.touch_origin(oid, name, 100.0)
        store.conn.execute("UPDATE origins SET state='fresh', last_seen_at=? WHERE origin_id=?",
                           (100.0 if oid == "live" else 200.0, oid))   # the dead one looks best
        store.conn.execute(
            "INSERT INTO rentries(origin_id,content_key,kind,title,sort_title,folder_label,rel_path)"
            " VALUES(?,?,?,?,?,?,?)", (oid, key, "video", "Film", "film", "Films", "Film (1999).mkv"))
    store.conn.commit()
    mesh.fetcher.set_peers([{"id": "dead", "url": "http://127.0.0.1:9/", "name": "Dead PC"},
                            {"id": "live", "url": url, "name": "Study PC"}])
    sources = mesh.remote_sources(key)
    assert [s["origin"] for s in sources] == ["dead", "live"] and sources[0]["suffix"] == ".mkv"
    monkeypatch.setattr(hf, "fetch", lambda u, k, d, **kw: _real_fetch(u, k, d, min_free=0, **kw))
    path = mesh.fetch_remote(key, sources[0])
    assert path.read_bytes() == DATA and path.parent == mesh.cache_dir
    assert mesh.remote_source("qh:" + "9" * 32) is None
    with pytest.raises(hf.FetchError):
        mesh.fetch_remote("qh:" + "9" * 32, {**sources[0], "url": "http://127.0.0.1:9/"})


_real_fetch = hf.fetch
