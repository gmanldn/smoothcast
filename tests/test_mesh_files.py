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


@pytest.mark.parametrize("range_header,status,start,end,size,valid", [
    (None, 200, 0, 99, 100, True),
    (None, 206, 0, 99, 100, False),
    ("bytes=0-", 206, 0, 99, 100, True),
    ("bytes=10-20", 206, 10, 20, 100, True),
    ("bytes=10-999", 206, 10, 99, 100, True),
    ("bytes=-15", 206, 85, 99, 100, True),
    ("bytes=-150", 206, 0, 99, 100, True),
    ("bytes=0-", 200, 0, 99, 100, False),
    ("bytes=10-", 206, 0, 89, 100, False),
    ("bytes=10-", 206, 11, 99, 100, False),
    ("bytes=-15", 206, 0, 14, 100, False),
    ("bytes=20-10", 206, 20, 99, 100, False),
    ("bytes=100-", 206, 100, 100, 100, False),
    ("bytes=1-2,3-4", 206, 1, 2, 100, False),
    ("bytes=-0", 206, 0, 99, 100, False),
])
def test_proxy_response_must_match_browser_requested_range(
        range_header, status, start, end, size, valid):
    assert mesh_files._matches_request(range_header, status, start, end, size) is valid


def test_proxy_closes_downstream_when_upstream_exhausts_retry_budget():
    from io import BytesIO

    class FailingReply:
        def read(self, _size):
            raise OSError("disconnected")

    class Connection:
        def close(self):
            pass

    class Client:
        close_connection = False
        wfile = BytesIO()

    client = Client()
    proxy = mesh_files.MeshFiles(lambda _k: None, lambda _k: [], lambda _k: None)
    proxy._open = lambda *_args: (_ for _ in ()).throw(OSError("offline"))
    proxy._pump(client, "qh:" + "a" * 32, "http://127.0.0.1/",
                Connection(), FailingReply(), 0, 128, "128", None)
    assert client.close_connection is True
    assert client.wfile.getvalue() == b""


@pytest.mark.parametrize("phase", ["request", "response"])
def test_mesh_upstream_connection_closed_on_handshake_error(phase):
    closed = []
    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            if phase == "request":
                raise OSError("send failure")

        def getresponse(self):
            raise OSError("headers failure")

        def close(self):
            closed.append(True)

    proxy = mesh_files.MeshFiles(lambda _k: None, lambda _k: [],
                                 lambda _k: None, connect=Connection)
    with pytest.raises(OSError):
        proxy._open("http://127.0.0.1:8080", "qh:" + "b" * 32, None, False)
    assert closed == [True]


def test_mesh_origin_generation_changes_on_same_size_replacement(origin):
    """The validator tracks the open file, not just its byte count."""
    harness, idx, key = origin
    path = idx.resolve_path(key)
    assert path is not None
    status, headers, body = get(harness, f"/mesh/file/{key}")
    assert status == 200 and body == DATA
    generation = headers["X-SmoothCast-Generation"]
    assert len(generation) == 64
    replacement = path.with_name("new-media.tmp")
    replacement.write_bytes(b"X" * len(DATA))
    os.replace(replacement, path)
    status, headers, body = get(harness, f"/mesh/file/{key}")
    assert status == 200 and body == b"X" * len(DATA)
    assert headers["X-SmoothCast-Generation"] != generation


def test_proxy_retry_rejects_changed_generation_even_if_size_is_identical():
    first = _ResumeReply()
    first.values["X-SmoothCast-Generation"] = "old-generation"
    assert mesh_files._valid_resume(first, 100, 199, "1000",
                                    '"same"', "old-generation")
    first.values["X-SmoothCast-Generation"] = "new-generation"
    assert not mesh_files._valid_resume(first, 100, 199, "1000",
                                        '"same"', "old-generation")
    first.values.pop("X-SmoothCast-Generation")
    assert not mesh_files._valid_resume(first, 100, 199, "1000",
                                        '"same"', "old-generation")
    # Legacy peers without the new header remain compatible; their identity
    # cannot be guaranteed through this mechanism.
    assert mesh_files._valid_resume(first, 100, 199, "1000", '"same"')


def test_proxy_exposes_mesh_generation_for_later_range_requests(origin):
    home, _idx, key = origin
    proxy = RoomHarness(count=1)
    try:
        origin_port = home.server.server_address[1]
        proxy.server.mesh_files = mesh_files.MeshFiles(
            lambda _key: None, lambda _key: ["home"],
            lambda _origin: f"http://127.0.0.1:{origin_port}/")
        status, headers, body = get(proxy, f"/mesh/file/{key}",
                                    {"Range": "bytes=0-1023"})
        assert status == 206 and body == DATA[:1024]
        assert len(headers["X-SmoothCast-Generation"]) == 64
    finally:
        proxy.close()


def test_mesh_stream_stops_instead_of_mixing_replaced_file_bytes():
    """A same-length replacement after an upstream drop must truncate safely."""
    from io import BytesIO

    class Reply:
        def __init__(self, payload, generation, *, broken=False):
            self.status = 206
            self.payload = payload
            self.generation = generation
            self.broken = broken

        def getheader(self, name):
            return {
                "Content-Range": "bytes 4-7/8",
                "Content-Length": "4",
                "X-SmoothCast-Generation": self.generation,
            }.get(name)

        def read(self, _n):
            if self.broken:
                raise OSError("origin disconnected")
            self.broken = True
            return self.payload

    class Connection:
        def close(self):
            pass

    class Client:
        close_connection = False

        def __init__(self):
            self.wfile = BytesIO()

    client = Client()
    proxy = mesh_files.MeshFiles(lambda _key: None, lambda _key: [], lambda _peer: None)
    retried = []
    def reopen(_url, _key, requested_range, _head):
        retried.append(requested_range)
        return Connection(), Reply(b"WXYZ", "new-generation")
    proxy._open = reopen
    class Initial:
        def __init__(self):
            self.called = False

        def read(self, _n):
            if not self.called:
                self.called = True
                return b"ABCD"
            raise OSError("upstream vanished")

    proxy._pump(client, "qh:" + "a" * 32, "http://127.0.0.1/",
                Connection(), Initial(), 0, 8, "8", None, "old-generation")
    assert retried == ["bytes=4-7"]
    assert client.wfile.getvalue() == b"ABCD"
    assert client.close_connection is True
