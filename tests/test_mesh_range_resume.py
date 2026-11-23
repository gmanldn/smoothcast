"""#567: byte-identical resume, boundaries, If-Range, suffix, 416 and sparse files.

Loopback only, deterministic fault injection, no GTK/TV/Internet.
"""
from __future__ import annotations

from http.client import HTTPConnection, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_files
from test_room_conformance import RoomHarness

MIB = 1024 * 1024
DATA = os.urandom(2 * MIB + 17)
KEY = "qh:" + "d" * 32


def fetch(harness, headers=None, method="GET", key=KEY):
    port = harness.server.server_address[1]
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, f"/mesh/file/{key}",
                 headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    reply = conn.getresponse()
    try:
        body = reply.read()
    except IncompleteRead as exc:
        body = exc.partial
        return reply.status, dict(reply.getheaders()), body, True
    finally:
        conn.close()
    return reply.status, dict(reply.getheaders()), body, False


def span(header: str, size: int):
    first, last = header[6:].split("-")
    if first:
        return int(first), min(int(last) if last else size - 1, size - 1)
    return max(0, size - int(last)), size - 1


class Origin(BaseHTTPRequestHandler):
    """Range-capable origin; drops once after ``drop_after`` body bytes."""
    protocol_version = "HTTP/1.1"
    data = DATA
    drop_after: int | None = None
    etag = '"stable-strong"'
    etag_after_drop = None  # simulate the file changing during the stream
    dropped = False
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        cls = type(self)
        cls.seen.append(self.headers.get("Range"))
        header = self.headers.get("Range")
        size = len(cls.data)
        first, last = span(header, size) if header else (0, size - 1)
        body = cls.data[first:last + 1]
        etag = cls.etag_after_drop if cls.dropped and cls.etag_after_drop else cls.etag
        self.send_response(206 if header else 200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        if header:
            self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.end_headers()
        if cls.drop_after is not None and not cls.dropped and len(body) > cls.drop_after:
            cls.dropped = True
            self.wfile.write(body[:cls.drop_after])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


def run_origin(**attrs):
    handler = type("O", (Origin,), {"seen": [], "dropped": False, **attrs})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = RoomHarness(count=1)
    proxy.server.mesh_files = mesh_files.MeshFiles(
        lambda k: None, lambda k: ["o"],
        lambda o: f"http://127.0.0.1:{server.server_address[1]}/")
    return handler, server, proxy


def close(server, proxy):
    proxy.close()
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("drop_after", [
    1, 4096, MIB - 1, MIB, MIB + 1, 2 * MIB, len(DATA) - 1,
])
def test_full_get_resumes_byte_identically_at_any_offset(drop_after):
    handler, server, proxy = run_origin(drop_after=drop_after)
    try:
        status, _h, body, short = fetch(proxy)
        assert (status, short) == (200, False)
        assert hashlib.sha256(body).hexdigest() == hashlib.sha256(DATA).hexdigest()
        # A partial chunk is discarded, never spliced: resume at the last whole chunk.
        resume = drop_after // MIB * MIB
        assert handler.dropped and handler.seen[-1] == f"bytes={resume}-{len(DATA) - 1}"
    finally:
        close(server, proxy)


@pytest.mark.parametrize("rng", [
    "bytes=0-", "bytes=5-", f"bytes={MIB}-{MIB + 99}", f"bytes={MIB - 1}-{MIB}",
    "bytes=-1", "bytes=-1000", f"bytes=-{len(DATA)}", f"bytes=0-{len(DATA) + 50}",
])
@pytest.mark.parametrize("drop_after", [None, 1, 37])
def test_range_forms_resume_to_the_exact_requested_slice(rng, drop_after):
    handler, server, proxy = run_origin(drop_after=drop_after)
    try:
        first, last = span(rng, len(DATA))
        status, headers, body, short = fetch(proxy, {"Range": rng})
        assert (status, short) == (206, False)
        assert body == DATA[first:last + 1]
        assert headers["Content-Range"] == f"bytes {first}-{last}/{len(DATA)}"
        assert headers["Content-Length"] == str(last - first + 1)
    finally:
        close(server, proxy)


def test_one_byte_object_whole_and_suffix():
    handler, server, proxy = run_origin(data=b"Z")
    try:
        assert fetch(proxy)[::2][0:2] == (200, b"Z")
        status, headers, body, _s = fetch(proxy, {"Range": "bytes=-1"})
        assert (status, body, headers["Content-Range"]) == (206, b"Z", "bytes 0-0/1")
        # This fixture cannot say 416; a bogus 206 must never be forwarded.
        assert fetch(proxy, {"Range": "bytes=1-"})[0] != 206
    finally:
        close(server, proxy)


@pytest.mark.parametrize("etag_after", ['"changed"', 'W/"weak"', None])
def test_file_changed_mid_stream_truncates_and_never_splices(etag_after):
    # etag None == validator vanished after the drop: still fail closed.
    handler, server, proxy = run_origin(drop_after=700_000, etag_after_drop=etag_after or "")
    if etag_after is None:
        handler.etag_after_drop = None
        handler.etag = 'W/"weak"'  # weak-only identity cannot prove byte identity
    try:
        status, _h, body, short = fetch(proxy)
        assert status == 200 and short is True
        assert body == DATA[:len(body)] and len(body) < len(DATA)
    finally:
        close(server, proxy)


def test_changed_total_size_mid_stream_truncates():
    handler, server, proxy = run_origin(drop_after=1000)
    try:
        original_get = handler.do_GET

        def shrink(self):
            if type(self).dropped:
                type(self).data = DATA[:-5]
            original_get(self)
        handler.do_GET = shrink
        status, _h, body, short = fetch(proxy)
        assert status == 200 and short is True
        assert body == DATA[:len(body)] and len(body) < len(DATA)
    finally:
        close(server, proxy)


def test_retry_budget_is_bounded_when_origin_keeps_dropping():
    class Always(Origin):
        def do_GET(self):
            type(self).seen.append(self.headers.get("Range"))
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Length", str(len(DATA)))
            self.send_header("ETag", self.etag)
            if self.headers.get("Range"):
                first = span(self.headers["Range"], len(DATA))[0]
                self.send_header("Content-Range", f"bytes {first}-{len(DATA) - 1}/{len(DATA)}")
                self.send_header("Content-Length", str(len(DATA) - first))
            self.end_headers()
            self.wfile.flush()
            self.connection.close()

    Always.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Always)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proxy = RoomHarness(count=1)
    proxy.server.mesh_files = mesh_files.MeshFiles(
        lambda k: None, lambda k: ["o"],
        lambda o: f"http://127.0.0.1:{server.server_address[1]}/")
    try:
        status, _h, body, short = fetch(proxy)
        assert status == 200 and short is True and body == b""
        assert len(Always.seen) <= 1 + mesh_files.MAX_RETRIES
    finally:
        close(server, proxy)


def test_if_range_is_never_answered_with_a_partial_body():
    handler, server, proxy = run_origin()
    try:
        status, headers, body, _s = fetch(
            proxy, {"Range": "bytes=10-19", "If-Range": '"stable-strong"'})
        assert status == 200 and body == DATA and "Content-Range" not in headers
        assert handler.seen == [None]  # the Range never reached the peer either
    finally:
        close(server, proxy)


@pytest.fixture
def sparse_chain(tmp_path):
    """1 GiB sparse file behind a real origin, reached through a real proxy."""
    size = 1 << 30
    path = tmp_path / "huge.bin"
    with open(path, "wb") as f:
        f.truncate(size)
    with open(path, "r+b") as f:
        f.seek(size - 4)
        f.write(b"TAIL")
    origin = RoomHarness(count=1)
    origin.server.mesh_files = mesh_files.MeshFiles(
        lambda k: path if k == KEY else None, lambda k: [], lambda o: None)
    proxy = RoomHarness(count=1)
    proxy.server.mesh_files = mesh_files.MeshFiles(
        lambda k: None, lambda k: ["o"],
        lambda o: f"http://127.0.0.1:{origin.server.server_address[1]}/")
    yield proxy, size
    proxy.close()
    origin.close()


def test_one_gib_sparse_ranges_and_416_through_the_proxy(sparse_chain):
    proxy, size = sparse_chain
    status, headers, body, _s = fetch(proxy, {"Range": "bytes=-4"})
    assert (status, body) == (206, b"TAIL")
    assert headers["Content-Range"] == f"bytes {size - 4}-{size - 1}/{size}"
    status, headers, body, _s = fetch(proxy, {"Range": f"bytes={size - 1}-"})
    assert (status, len(body)) == (206, 1)
    status, headers, body, _s = fetch(proxy, {"Range": f"bytes={MIB * 1000}-{MIB * 1000 + 3}"})
    assert (status, body) == (206, b"\0" * 4)
    status, headers, body, _s = fetch(proxy, {"Range": f"bytes={size}-"})
    assert (status, body) == (416, b"")
    assert headers["Content-Range"] == f"bytes */{size}"


def test_local_if_range_also_returns_the_whole_object(tmp_path):
    path = tmp_path / "small.bin"
    path.write_bytes(DATA[:5000])
    origin = RoomHarness(count=1)
    origin.server.mesh_files = mesh_files.MeshFiles(
        lambda k: path, lambda k: [], lambda o: None)
    try:
        status, headers, body, _s = fetch(
            origin, {"Range": "bytes=1-2", "If-Range": '"anything"'})
        assert (status, body) == (200, DATA[:5000])
    finally:
        origin.close()
