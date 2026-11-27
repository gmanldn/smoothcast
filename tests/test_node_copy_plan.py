import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_copy_plan as cp

DATA = b"0123456789" * 100
DIG = hashlib.sha256(DATA).hexdigest()
FREE = 10**10


def mk(**k):
    return cp.Incoming("t", len(DATA), DIG, consent=True, free_bytes=FREE, **k)


def test_happy_path_verifies_digest():
    t = mk()
    assert t.chunk(0, DATA[:400])[0] and t.chunk(400, DATA[400:])[0]
    assert t.progress() == 1.0 and t.finish() == (True, "") and t.state == cp.DONE


def test_interrupted_transfer_resumes_and_rejects_gaps_and_overruns():
    t = mk(); t.chunk(0, DATA[:300])
    assert t.resume_from() == 300 and not t.chunk(500, DATA[500:])[0]
    r = mk(); r.restart_after_crash(DATA[:300])
    assert r.chunk(300, DATA[300:])[0] and r.finish()[0]
    assert not mk().chunk(0, DATA + b"x")[0]


def test_corrupt_or_short_copy_is_discarded():
    t = mk(); t.chunk(0, b"x" * len(DATA))
    assert not t.finish()[0] and t.state == cp.FAILED
    s = mk(); s.chunk(0, DATA[:10]); assert "incomplete" in s.finish()[1]


def test_consent_quota_duplicate_cancel_revoke():
    assert cp.Incoming("t", 5, DIG, consent=False, free_bytes=FREE).state == cp.FAILED
    assert "free space" in cp.Incoming("t", 10**9, DIG, consent=True, free_bytes=10**9).reason
    d = mk(known_digests={DIG}); assert d.state == cp.DONE and "Already saved" in d.reason
    c = mk(); c.chunk(0, DATA[:5]); c.cancel(); assert c.state == cp.CANCELLED and not c.chunk(5, DATA[5:10])[0]
    r = mk(); r.chunk(0, DATA[:5]); r.revoke(); assert r.state == cp.FAILED and "withdrawn" in r.reason
