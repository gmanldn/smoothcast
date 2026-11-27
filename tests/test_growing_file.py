import hashlib
import os
import struct
import threading

import pytest

from src import growing_file as G


class Clk:
    t = 0.0

    def __call__(self):
        return self.t


def box(kind, payload=b""):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def test_consumer_sees_exact_bytes_at_producer_rates(tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 17)
    for chunk in (256 * 1024, 700 * 1024):                      # slow-ish and fast producers
        g = G.Growing(str(tmp_path / f"f{chunk}"), len(data), "id")
        got, errs = bytearray(), []

        def consume():
            pos = 0
            try:
                while True:
                    b = g.read(pos, 512 * 1024, wait=5)
                    if not b:
                        break
                    got.extend(b)
                    pos += len(b)
            except Exception as e:                              # pragma: no cover
                errs.append(e)

        t = threading.Thread(target=consume)
        t.start()
        for off in range(0, len(data), chunk):
            g.append(data[off:off + chunk], off, "id")
        t.join(10)
        assert not errs and hashlib.sha256(got).digest() == hashlib.sha256(data).digest() and g.complete


def test_retry_overlap_is_trimmed_gap_refused_and_overrun_refused(tmp_path):
    g = G.Growing(str(tmp_path / "a"), 10, "id")
    g.append(b"01234", 0, "id")
    assert g.append(b"34567", 3, "id") == 8                    # retry overlapping bytes 3..4
    with pytest.raises(ValueError, match="gap"):
        g.append(b"x", 9, "id")
    with pytest.raises(ValueError, match="past"):
        g.append(b"xxx", 8, "id")
    g.append(b"89", 8, "id")
    assert open(g.path, "rb").read() == b"0123456789"


def test_stall_then_resume_at_exact_offset(tmp_path):
    c = Clk()
    g = G.Growing(str(tmp_path / "a"), 10, "id", clock=c)
    g.append(b"abc", 0, "id")
    assert g.read(0, 99) == b"abc"
    c.t = 31
    with pytest.raises(G.Stalled):
        g.read(3, 1, wait=0.2)
    assert g.state()["waiting_for_source"]
    g.append(b"defghij", 3, "id")
    assert g.read(3, 99) == b"defghij" and g.read(10, 1) == b""


def test_cancel_and_stale_source_wake_waiting_reader(tmp_path):
    g = G.Growing(str(tmp_path / "a"), 10, "id")
    out = []
    t = threading.Thread(target=lambda: out.append(_catch(lambda: g.read(0, 1, wait=5))))
    t.start()
    g.cancel()
    t.join(5)
    assert isinstance(out[0], G.Cancelled)
    with pytest.raises(G.Cancelled):
        g.append(b"a", 0, "id")
    h = G.Growing(str(tmp_path / "b"), 10, "id")
    with pytest.raises(G.Superseded):
        h.append(b"a", 0, "other")
    with pytest.raises(G.Superseded):
        h.read(0, 1)


def _catch(fn):
    try:
        return fn()
    except Exception as e:
        return e


def test_seek_is_honest(tmp_path):
    g = G.Growing(str(tmp_path / "a"), 10, "id")
    g.append(b"abcde", 0, "id")
    assert g.seekable_to(4) and not g.seekable_to(5)
    g.append(b"fghij", 5, "id")
    assert g.seekable_to(9)


def test_mp4_gate():
    ftyp, moov, mdat = box(b"ftyp", b"x" * 12), box(b"moov", b"m" * 100), box(b"mdat", b"d" * 50)
    ok = ftyp + moov + mdat
    assert G.mp4_early_ready(ok, len(ok)) == "ready"
    assert G.mp4_early_ready(ftyp + moov[:40], len(ftyp) + 40) == "wait"      # late/partial moov
    assert G.mp4_early_ready(ftyp + mdat + moov, 999) == "finish_first"       # non-faststart
    assert G.mp4_early_ready(ftyp[:4], 4) == "wait"
    assert G.mp4_early_ready(ftyp + struct.pack(">I4s", 0, b"free"), 999) == "finish_first"


def test_cleanup_waits_for_consumers_and_recover_never_completes_partial(tmp_path):
    g = G.Growing(str(tmp_path / "a"), 4, "id")
    g.append(b"ab", 0, "id")
    assert G.recover(g.path, 4, 2) == "partial"
    assert not G.cleanup(g, 1) and os.path.exists(g.path)
    g.append(b"cd", 2, "id")
    assert G.recover(g.path, 4, 4) == "complete" and G.recover(g.path, 4, 0) == "partial"
    assert G.cleanup(g, 0) and not os.path.exists(g.path) and G.recover(g.path, 4, 4) == "missing"
