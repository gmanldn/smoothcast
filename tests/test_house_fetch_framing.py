"""Remote copy framing and cleanup regressions; no real receivers or network."""
import pytest

import fingerprint
import house_fetch as hf


class Reply:
    def __init__(self, status, headers, chunks=()):
        self.status = status
        self.headers = headers
        self.chunks = iter(chunks)

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, size):
        return next(self.chunks, b"")


class Connection:
    def __init__(self, reply):
        self.reply = reply
        self.closed = False

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return self.reply

    def close(self):
        self.closed = True


@pytest.mark.parametrize("headers", [
    {"Content-Length": "3", "Content-Range": "bytes 0-2/6"},
    {"Content-Length": "3", "Content-Range": "bytes 3-5/7"},
    {"Content-Length": "2", "Content-Range": "bytes 3-5/6"},
    {"Content-Length": "3"},
])
def test_invalid_resume_never_appends_and_closes_connection(tmp_path, headers):
    key = "qh:" + "a" * 32
    final = hf.cache_path(tmp_path, key, ".mkv")
    part = final.with_name(final.name + ".part")
    part.write_bytes(b"abc")
    conn = Connection(Reply(206, headers, [b"def"]))
    with pytest.raises(hf.FetchError, match="resume range"):
        hf.fetch("http://127.0.0.1:80/", key, tmp_path, suffix=".mkv",
                 connect=lambda *a, **kw: conn, min_free=0)
    assert conn.closed
    assert part.read_bytes() == b"abc"
    assert not final.exists()


def test_rejected_origin_closes_connection(tmp_path):
    conn = Connection(Reply(404, {}))
    with pytest.raises(hf.FetchError):
        hf.fetch("http://127.0.0.1:80/", "qh:" + "a" * 32, tmp_path,
                 connect=lambda *a, **kw: conn, min_free=0)
    assert conn.closed


def test_cancelled_cache_hit_is_not_delivered(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    key = fingerprint.quick_hash(source)
    final = hf.cache_path(tmp_path, key, ".bin")
    source.rename(final)
    with pytest.raises(hf.FetchError, match="Cancelled"):
        hf.fetch("http://127.0.0.1:80/", key, tmp_path, cancelled=lambda: True)
    assert final.read_bytes() == b"abc"


def test_valid_resume_returns_verified_file_and_closes_connection(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"abcdef")
    key = fingerprint.quick_hash(source)
    final = hf.cache_path(tmp_path, key, ".bin")
    final.with_name(final.name + ".part").write_bytes(b"abc")
    conn = Connection(Reply(206, {"Content-Length": "3",
                                  "Content-Range": "bytes 3-5/6"}, [b"def"]))
    path = hf.fetch("http://127.0.0.1:80/", key, tmp_path,
                    connect=lambda *a, **kw: conn, min_free=0)
    assert path == final and path.read_bytes() == b"abcdef"
    assert conn.closed
