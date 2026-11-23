"""#410: library replication responses, rate limiting and HTTP routes."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_folders as lf
import library_index_v2 as li
import library_replication as lr


def origin(tmp_path, shared=True, files=5):
    lib = tmp_path / "lib"
    lib.mkdir()
    for i in range(files):
        (lib / f"song{i}.mp3").write_bytes(bytes([i + 1]) * (40 + i))
    idx = li.LibraryIndexer(tmp_path / "o.sqlite3", probe=lambda p: {})
    idx.set_folders([lf.LibraryFolder("f_1", str(lib), "Music", "music", shared)])
    idx.scan_all()
    return idx, lib


def apply(replica: dict, changes):
    for change in changes:
        if change["op"] == "upsert":
            replica[change["entry"]["content_key"]] = change["entry"]
        else:
            replica.pop(change["content_key"], None)


def test_changes_pages_are_ordered_bounded_and_complete(tmp_path):
    idx, _lib = origin(tmp_path, files=7)
    _o, epoch, _s = idx.generation()
    seen, since = [], 0
    while True:
        status, body = lr.build_changes_response(idx, epoch, since, 3)
        assert status == 200 and len(body["changes"]) <= 3
        seen += [c["seq"] for c in body["changes"]]
        since = body["to"]
        if not body["more"]:
            break
    assert seen == sorted(seen) and len(seen) == 7 == len(set(seen))


def test_snapshot_plus_changes_reproduces_shared_set(tmp_path):
    idx, lib = origin(tmp_path, files=6)
    replica: dict = {}
    cursor, at_seq, epoch = None, 0, ""
    while True:
        status, page = lr.build_snapshot_response(idx, cursor, 4)
        assert status == 200
        for entry in page["entries"]:
            replica[entry["content_key"]] = entry
        epoch, at_seq, cursor = page["epoch"], page["at_seq"], page["next"]
        if not cursor:
            break
    (lib / "new.mp3").write_bytes(b"z" * 99)           # change after the snapshot
    (lib / "song0.mp3").unlink()
    idx.scan_all()
    status, body = lr.build_changes_response(idx, epoch, at_seq)
    apply(replica, body["changes"])
    expected = {e["content_key"] for e in idx.snapshot_page(None, 5000, shared_only=True)[0]}
    assert set(replica) == expected and len(expected) == 6


def test_stale_epoch_and_compaction_return_410(tmp_path):
    idx, _lib = origin(tmp_path)
    status, body = lr.build_changes_response(idx, "old-epoch", 0)
    assert status == 410 and body["epoch"] == idx.generation()[1]
    idx._set_meta("oldest_seq", "9")
    status, _ = lr.build_changes_response(idx, idx.generation()[1], 2)
    assert status == 410
    assert lr.build_changes_response(idx, idx.generation()[1], "x")[0] == 400


def test_no_absolute_paths_and_unshared_folders_hidden(tmp_path):
    idx, lib = origin(tmp_path)
    blob = json.dumps(lr.build_snapshot_response(idx, None)[1]) + json.dumps(
        lr.build_changes_response(idx, idx.generation()[1], 0)[1])
    assert str(tmp_path) not in blob and "mtime_ns" not in blob and "ino" not in blob
    assert "Music" in blob and "song1.mp3" in blob
    private, _ = origin(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, shared=False)
    assert lr.build_snapshot_response(private, None)[1]["entries"] == []
    assert lr.build_changes_response(private, private.generation()[1], 0)[1]["changes"] == []


def test_unsharing_emits_deletes_and_resharing_upserts(tmp_path):
    idx, lib = origin(tmp_path, files=3)
    epoch, seq = idx.generation()[1:]
    folder = idx._folders[0]
    idx.set_folders([lf.LibraryFolder(folder.id, folder.path, folder.label, folder.kind, False)])
    changes = lr.build_changes_response(idx, epoch, seq)[1]["changes"]
    assert [c["op"] for c in changes] == ["delete"] * 3
    seq = idx.generation()[2]
    idx.set_folders([folder])
    changes = lr.build_changes_response(idx, epoch, seq)[1]["changes"]
    assert [c["op"] for c in changes] == ["upsert"] * 3


def test_validate_entry():
    good = {"content_key": "qh:1", "kind": "video", "title": "T", "year": 2000}
    assert lr.validate_entry(good)
    assert not lr.validate_entry({**good, "title": "x" * 600})
    assert not lr.validate_entry({**good, "extra": {"nested": 1}})
    assert not lr.validate_entry({"kind": "video"}) and not lr.validate_entry("x")


def test_rate_limiter_returns_retry_after():
    now = [0.0]
    limiter = lr.RateLimiter(rate=10, burst=3, clock=lambda: now[0])
    assert [limiter.allow("p") for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = limiter.allow("p")
    assert wait > 0
    now[0] += 0.2
    assert limiter.allow("p") == 0.0 and limiter.allow("other") == 0.0


def test_http_routes_gzip_and_429(tmp_path):
    from test_room_conformance import RoomHarness
    idx, _lib = origin(tmp_path)
    harness = RoomHarness(count=1)
    try:
        harness.server.library_replication = lr.Replication(
            idx, lr.RateLimiter(rate=0.001, burst=3))
        status, body, _ = harness.request("GET", "/mesh/library/generation")
        assert status == 200 and body["count"] == 5 and "search.v1" in body["caps"]
        epoch = body["epoch"]
        status, body, headers = harness.request(
            "GET", f"/mesh/library/changes?epoch={epoch}&since=0")
        assert status == 200 and len(body["changes"]) == 5
        from http.client import HTTPConnection
        conn = HTTPConnection("127.0.0.1", harness.server.server_address[1], timeout=3)
        conn.request("GET", "/mesh/library/snapshot",
                     headers={"Host": harness.host, "Accept-Encoding": "gzip"})
        reply = conn.getresponse()
        assert reply.status == 200 and reply.getheader("Content-Encoding") == "gzip"
        assert len(json.loads(gzip.decompress(reply.read()))["entries"]) == 5
        status, body, headers = harness.request("GET", "/mesh/library/generation")
        assert status == 429 and "Retry-After" in headers
    finally:
        harness.close()


def test_gzip_encoding_round_trip():
    body, headers = lr.encode({"a": 1}, True)
    assert headers == {"Content-Encoding": "gzip"} and json.loads(gzip.decompress(body)) == {"a": 1}
