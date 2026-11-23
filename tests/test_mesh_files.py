"""#422: content-key file serving, Range proxying, resume and loop guard."""
from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_folders as lf
import library_index_v2 as li
import mesh_files
from test_room_conformance import RoomHarness

DATA = os.urandom(2_600_000)
SHA = hashlib.sha256(DATA).hexdigest()


def origin_index(tmp_path, shared=True):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "Film (2001).mkv").write_bytes(DATA)
    idx = li.LibraryIndexer(tmp_path / "o.sqlite3", probe=lambda p: {})
    idx.set_folders([lf.LibraryFolder("f_1", str(lib), "Films", "video", shared)])
    idx.scan_all()
    key = idx.snapshot_page(None)[0][0]["content_key"]
    return idx, key


def get(harness_or_port, path, headers=None, method="GET"):
    port = harness_or_port.server.server_address[1] if hasattr(harness_or_port, "server") else harness_or_port
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    reply = conn.getresponse()
    return reply.status, dict(reply.getheaders()), reply.read()


@pytest.fixture
def origin(tmp_path):
    idx, key = origin_index(tmp_path)
    harness = RoomHarness(count=1)
    harness.server.mesh_files = mesh_files.MeshFiles(idx.resolve_path, lambda k: [], lambda o: None)
    yield harness, idx, key
    harness.close()


def test_origin_serves_full_and_ranged_bytes(origin):
    harness, _idx, key = origin
    status, headers, body = get(harness, f"/mesh/file/{key}")
    assert status == 200 and hashlib.sha256(body).hexdigest() == SHA
    assert headers["Accept-Ranges"] == "bytes"
    status, headers, body = get(harness, f"/mesh/file/{key}", {"Range": "bytes=100-199"})
    assert status == 206 and body == DATA[100:200]
    assert headers["Content-Range"] == f"bytes 100-199/{len(DATA)}"
    status, _h, body = get(harness, f"/mesh/file/{key}", {"Range": "bytes=-50"})
    assert status == 206 and body == DATA[-50:]
    status, _h, _b = get(harness, f"/mesh/file/{key}", {"Range": "bytes=999999999-"})
    assert status == 416
    status, headers, body = get(harness, f"/mesh/file/{key}", method="HEAD")
    assert status == 200 and body == b"" and headers["Content-Length"] == str(len(DATA))


@pytest.mark.parametrize("path", ["/mesh/file/", "/mesh/file/../etc/passwd", "/mesh/file/qh:xyz",
                                  "/mesh/file/qh:" + "0" * 32])
def test_bad_unknown_or_traversal_keys_are_404(origin, path):
    assert get(origin[0], path)[0] == 404


def test_unshared_folder_is_not_served(tmp_path):
    idx, key = origin_index(tmp_path, shared=False)
    harness = RoomHarness(count=1)
    try:
        harness.server.mesh_files = mesh_files.MeshFiles(idx.resolve_path, lambda k: [], lambda o: None)
        assert get(harness, f"/mesh/file/{key}")[0] == 404
    finally:
        harness.close()


def test_proxy_streams_exact_bytes_from_the_home_node(origin):
    b_harness, _idx, key = origin
    proxy = RoomHarness(count=1)
    try:
        port_b = b_harness.server.server_address[1]
        proxy.server.mesh_files = mesh_files.MeshFiles(
            lambda k: None, lambda k: ["b"], lambda o: f"http://127.0.0.1:{port_b}/")
        status, _h, body = get(proxy, f"/mesh/file/{key}")
        assert status == 200 and hashlib.sha256(body).hexdigest() == SHA
        status, headers, body = get(proxy, f"/mesh/file/{key}", {"Range": "bytes=1000000-1999999"})
        assert status == 206 and body == DATA[1_000_000:2_000_000]
        assert headers["Content-Range"] == f"bytes 1000000-1999999/{len(DATA)}"
        status, headers, body = get(proxy, f"/mesh/file/{key}", method="HEAD")
        assert status == 200 and body == b""
    finally:
        proxy.close()


def test_proxied_request_is_never_proxied_again(tmp_path):
    proxy = RoomHarness(count=1)
    try:
        calls = []
        proxy.server.mesh_files = mesh_files.MeshFiles(
            lambda k: None, lambda k: calls.append(k) or ["b"], lambda o: "http://127.0.0.1:9/")
        key = "qh:" + "a" * 32
        status, _h, _b = get(proxy, f"/mesh/file/{key}", {mesh_files.HOP_HEADER: "1"})
        assert status == 404 and calls == []
    finally:
        proxy.close()


def test_non_lan_peer_and_dead_peer_give_404(tmp_path):
    proxy = RoomHarness(count=1)
    try:
        key = "qh:" + "b" * 32
        for url in ("http://8.8.8.8:80/", "http://127.0.0.1:9/"):
            proxy.server.mesh_files = mesh_files.MeshFiles(lambda k: None, lambda k: ["p"], lambda o, u=url: u)
            assert get(proxy, f"/mesh/file/{key}")[0] == 404
    finally:
        proxy.close()


class Flaky(BaseHTTPRequestHandler):
    """Serves DATA with Range support but drops the connection mid-body once."""
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
        self.send_header("Content-Type", "video/x-matroska")
        if header:
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        self.end_headers()
        if Flaky.drops > 0 and start == 0:
            Flaky.drops -= 1
            self.wfile.write(body[:1_300_000])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


def test_proxy_resumes_from_the_current_offset_after_an_upstream_drop():
    Flaky.drops = 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = RoomHarness(count=1)
    try:
        proxy.server.mesh_files = mesh_files.MeshFiles(
            lambda k: None, lambda k: ["flaky"],
            lambda o: f"http://127.0.0.1:{server.server_address[1]}/")
        status, _h, body = get(proxy, "/mesh/file/qh:" + "c" * 32)
        assert status == 200 and hashlib.sha256(body).hexdigest() == SHA
        assert Flaky.drops == 0
    finally:
        proxy.close()
        server.shutdown()
        server.server_close()


def test_stream_concurrency_cap_returns_503(origin, monkeypatch):
    harness, _idx, key = origin
    import portal_media
    monkeypatch.setattr(portal_media, "_streams", threading.BoundedSemaphore(1))
    assert portal_media._streams.acquire(blocking=False)       # every slot is taken
    assert get(harness, f"/mesh/file/{key}")[0] == 503
    portal_media._streams.release()
    assert get(harness, f"/mesh/file/{key}")[0] == 200


class _ResumeReply:
    def __init__(self, status=206, start=100, end=199, total=1000,
                 length=100, etag='"same"'):
        self.status = status
        self.values = {
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(length),
            "ETag": etag,
        }

    def getheader(self, key):
        return self.values.get(key)


@pytest.mark.parametrize("change", [
    {"status": 200},
    {"start": 99},
    {"start": 101},
    {"end": 198},
    {"end": 200},
    {"total": 1001},
    {"total": "*"},
    {"length": 99},
    {"length": 101},
    {"etag": '"new"'},
])
def test_proxy_resume_rejects_changed_byte_identity(change):
    reply = _ResumeReply(**change)
    assert not mesh_files._valid_resume(reply, 100, 199, "1000", '"same"')


def test_proxy_resume_accepts_identical_range_and_rejects_missing_etag():
    reply = _ResumeReply()
    assert mesh_files._valid_resume(reply, 100, 199, "1000", '"same"')
    assert not mesh_files._valid_resume(reply, 101, 199, "1000", '"same"')
    reply.values.pop("ETag")
    assert not mesh_files._valid_resume(reply, 100, 199, "1000", '"same"')


def test_proxy_initial_range_rejects_invalid_upstream_response():
    """Invalid 206 is refused before committing downstream headers."""
    class FakeConnection:
        def close(self):
            pass

    class InvalidReply(_ResumeReply):
        pass

    fake = mesh_files.MeshFiles(lambda _k: None, lambda _k: [],
                                lambda _k: None)
    reply = InvalidReply(start=2, end=8, total=10, length=4)
    fake._open = lambda *_args: (FakeConnection(), reply)
    class Request:
        headers = {"Range": "bytes=2-8"}
    writes = []
    assert not fake._proxy(Request(), "qh:" + "a" * 32,
                           "http://127.0.0.1/", head=False,
                           write_headers=lambda *args: writes.append(args))
    assert writes == []
