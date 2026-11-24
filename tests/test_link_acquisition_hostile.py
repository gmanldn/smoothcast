"""#587 security audit: hostile links and torrent metadata fail closed.

Seeded, dependency-free, bounded, no network/GUI. Properties checked: only
``LinkError`` ever escapes, nothing is slow, and anything accepted is canonical.
"""
from __future__ import annotations

import hashlib
import random
import re
import string
import time

import pytest

import link_acquisition as la

VIDEO = re.compile(r"[A-Za-z0-9_-]{11}")
SEEDS = ("https://www.youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk",
         "https://www.youtube.com/shorts/abcdefghijk", "magnet:?xt=urn:btih:" + "a" * 40,
         "magnet:?xt=urn:btih:" + "A" * 32)
ALPHABET = string.printable + "‮İｙ​\x00\x7f\x85é%@:/?#&=[]\\"


def mutate(rnd: random.Random, seed: str) -> str:
    chars = list(seed)
    for _ in range(rnd.randint(0, 4)):
        op, pos = rnd.random(), rnd.randrange(len(chars) + 1)
        if op < 0.4:
            chars.insert(pos, rnd.choice(ALPHABET))
        elif op < 0.7 and chars:
            chars.pop(min(pos, len(chars) - 1))
        elif chars:
            chars[min(pos, len(chars) - 1)] = rnd.choice(ALPHABET)
    return "".join(chars)


def test_mutated_links_never_raise_anything_but_linkerror_and_are_canonical():
    rnd, accepted = random.Random(587), 0
    for _ in range(8000):
        value = mutate(rnd, rnd.choice(SEEDS))
        try:
            source = la.parse_link(value)
        except la.LinkError:
            continue
        accepted += 1
        if source.kind == "youtube":
            assert VIDEO.fullmatch(source.identity)
            assert source.url == "https://www.youtube.com/watch?v=" + source.identity
        else:
            assert re.fullmatch(r"[0-9a-f]{40}", source.identity)
            assert source.url == "magnet:?xt=urn:btih:" + source.identity
    assert accepted > 100  # the corpus really does exercise the accept path too


@pytest.mark.parametrize("value", [
    None, 5, b"https://youtu.be/abcdefghijk", [], {}, "x" * 10**6, "\ud800",
    "https://www.youtube.com:99999999999999/watch?v=abcdefghijk",
    "https://[::1/watch?v=abcdefghijk",
    "https://www.youtube.com@evil.example/watch?v=abcdefghijk",
    "https://evil.example/https://www.youtube.com/watch?v=abcdefghijk",
    "https://www.youtube.com.evil.example/watch?v=abcdefghijk",
    "https://www.youtube.com./watch?v=abcdefghijk",
    "https://www.youtube.com:8443/watch?v=abcdefghijk",
    "http://www.youtube.com/watch?v=abcdefghijk",
    "https://user:pw@www.youtube.com/watch?v=abcdefghijk",
    "https://www.youtube.com/watch?v=abcdefghijk&v=bbbbbbbbbbb",
    "https://www.youtube.com/watch?v=abcdefghijk\nhttps://evil.example",
    "https://www.youtube.com/watch?v=abcdefghijk;rm -rf /",
    "https://www.youtube.com/watch?v=-oops-oops-oops",
    "https://www.youtube.com/watch?v=abcdefghij",
    "https://www.youtube.com/playlist?list=PLabcdefghijk",
    "https://www.youtube.com/watch?v=abcdefghijk/../../x",
    "https://youtu.be/abcdefghijk/extra",
    "file:///etc/passwd", "ftp://youtube.com/watch?v=abcdefghijk",
    "magnet:?xt=urn:btih:" + "a" * 39, "magnet:?xt=urn:btih:" + "g" * 40,
    "magnet:?xt=urn:btih:" + "a" * 40 + "&xt=urn:btih:" + "b" * 40,
    "magnet:?xt=urn:btmh:1220" + "a" * 64,
    "magnet://evil.example/?xt=urn:btih:" + "a" * 40,
    "magnet:?" + "&".join(f"x{i}=1" for i in range(500)) + "&xt=urn:btih:" + "a" * 40,
])
def test_hostile_links_are_rejected_with_linkerror(value):
    with pytest.raises(la.LinkError) as exc:
        la.parse_link(value)
    assert 400 <= exc.value.status < 500 and exc.value.message


def test_magnet_extras_never_survive_canonicalisation():
    source = la.parse_link("magnet:?xt=urn:btih:" + "A" * 40 +
                           "&tr=http://127.0.0.1:1/announce&ws=http://169.254.169.254/&dn=../../x&x.pe=10.0.0.1:1")
    assert source.url == "magnet:?xt=urn:btih:" + "a" * 40


def bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:" % len(value) + value
    if isinstance(value, list):
        return b"l" + b"".join(map(bencode, value)) + b"e"
    return b"d" + b"".join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b"e"


def torrent(name=b"a.mp4", length=100, piece=16384, extra=None):
    info = {b"name": name, b"length": length, b"piece length": piece,
            b"pieces": b"x" * min(20 * max(1, -(-length // max(piece, 1))), 4096), **(extra or {})}
    return bencode({b"info": info}), hashlib.sha1(bencode(info)).hexdigest()


def inspect_quickly(raw, digest):
    started = time.perf_counter()
    try:
        return la.inspect_torrent(raw, digest)
    except la.LinkError:
        return None
    finally:
        assert time.perf_counter() - started < 1.0, "metadata parsing must stay bounded"


def test_mutated_and_random_torrent_metadata_only_raises_linkerror():
    rnd = random.Random(588)
    corpus = [torrent(), torrent(name="é.mp4".encode()), torrent(length=2**70), torrent(length=-1),
              torrent(piece=0), torrent(piece=2**60), torrent(name=b"\xff.mp4")]
    for _ in range(4000):
        raw, digest = rnd.choice(corpus)
        data = bytearray(raw)
        for _ in range(rnd.randint(1, 6)):
            pos, op = rnd.randrange(len(data)), rnd.random()
            if op < 0.5:
                data[pos] = rnd.randrange(256)
            elif op < 0.75:
                data.insert(pos, rnd.randrange(256))
            else:
                del data[pos]
        inspect_quickly(bytes(data), digest)
        inspect_quickly(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 80))), digest)


@pytest.mark.parametrize("label,raw", [
    ("deep lists", b"l" * 100_000 + b"e" * 100_000),
    ("deep dicts", b"d1:a" * 50_000),
    ("huge integer", b"d4:infod6:lengthi" + b"9" * 5000 + b"eee"),
    ("no delimiter", b"1" * 2_000_000),
    ("node flood ints", b"l" + b"i1e" * 39_990 + b"e"),
    ("node flood strings", b"l" + b"1:a" * 30_000 + b"e"),
    ("oversize", b"l" + b"i1e" * 800_000 + b"e"),
    ("string length lie", b"d4:infod4:name99999999:xee"),
])
def test_pathological_bencode_is_bounded_and_rejected(label, raw):
    assert inspect_quickly(raw, "0" * 40) is None


def test_wrong_infohash_and_private_torrents_are_never_authenticated():
    raw, digest = torrent()
    assert inspect_quickly(raw, "0" * 40) is None  # metadata not matching the magnet's hash
    assert inspect_quickly(raw, digest) is not None
    assert inspect_quickly(*torrent(extra={b"private": 1})) is None
    assert inspect_quickly(*torrent(extra={b"meta version": 2})) is None
    assert inspect_quickly(*torrent(extra={b"attr": b"l"})) is None


@pytest.mark.parametrize("name", [b"..", b"a/b.mp4", b"a\\b.mp4", b"C:x.mp4", b"CON.mp4", b"nul.mkv",
                                  b"trail.mp4.", b"sp.mp4 ", b"ctl\x01.mp4", b"x" * 200 + b".mp4", b""])
def test_unsafe_single_file_names_are_rejected(name):
    assert inspect_quickly(*torrent(name=name)) is None


class SpoofProvider:
    def capabilities(self):
        return {"youtube": True, "magnet": True}

    def acquire(self, source, root, stage, progress, cancelled):
        path = root / "film‮4pm\x7f​.mp4"
        path.write_bytes(b"data")
        return path


def test_displayed_title_strips_bidi_and_control_characters(tmp_path):
    delivered = []
    jobs = la.LinkJobs(tmp_path, SpoofProvider(), lambda owner, path: delivered.append(path),
                       lambda owner: True)
    try:
        jobs.submit("owner", "https://www.youtube.com/watch?v=abcdefghijk", "req-1")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            rows = jobs.snapshot()
            if rows and rows[0]["stage"] == "ready":
                break
            time.sleep(0.01)
        assert jobs.snapshot()[0]["stage"] == "ready" and len(delivered) == 1
        title = jobs.snapshot()[0]["title"]
        assert title and all(c.isprintable() for c in title)
        assert "‮" not in title and "\x7f" not in title and "​" not in title
        assert "/" not in title
    finally:
        jobs.close()
