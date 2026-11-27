import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import offline_rules as orl


def test_space_rule_and_meter():
    GB = 10**9
    assert orl.admit(2 * GB, 3 * GB)[0] is True and orl.admit(2 * GB, 2 * GB + 100)[0] is False
    assert "Free up" in orl.admit(5 * GB, GB)[1]
    assert orl.meter(4_200_000_000, 7_800_000_000) == "Using 4.2 GB of 12.0 GB free."


def test_eligible_unwatched_and_keep_next():
    eps = [{"key": f"e{i}"} for i in range(1, 8)]
    rule = {"unwatched_only": True, "keep_next": 3}
    assert [e["key"] for e in orl.eligible(eps, rule, {"e1", "e2"})] == ["e3", "e4", "e5"]
    assert len(orl.eligible(eps, {}, set())) == 7


def test_tidy_immediately_after_days_and_notice():
    d = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
    w = {"a": 0.0, "b": 0.0}
    assert orl.tidy(d, {"remove_after": "immediately"}, w, 1) == (["a", "b"], "Tidied 2 episodes")
    assert orl.tidy(d, {"remove_after": 7}, w, 6 * 86400) == ([], "")
    assert orl.tidy(d, {"remove_after": 7}, {"a": 0.0}, 7 * 86400) == (["a"], "Tidied 1 episode")
    assert orl.tidy(d, {"remove_after": None}, w, 10**9)[0] == []


def test_evicted_downloads_marked_and_range_resume_matches_sha():
    m = orl.reconcile({"a": {"state": "ready"}, "b": {"state": "ready"}}, {"a"})
    assert m["a"]["state"] == "ready" and m["b"]["state"] == "needs_redownload"
    data = bytes(range(256)) * 400
    part = data[:30000]
    hdr = orl.range_header(len(part), len(data)); assert hdr == "bytes=30000-"
    start = int(hdr.split("=")[1].rstrip("-"))
    assert hashlib.sha256(part + data[start:]).hexdigest() == hashlib.sha256(data).hexdigest()
    assert orl.range_header(len(data), len(data)) is None


def test_token_expires_and_is_bound_to_session_and_item():
    k = b"s" * 32; t = orl.sign(k, "qh:1", "sess", 1000)
    assert orl.verify(k, t, "qh:1", "sess", 1000 + orl.TOKEN_TTL_S)
    assert not orl.verify(k, t, "qh:1", "sess", 1000 + orl.TOKEN_TTL_S + 1)
    assert not orl.verify(k, t, "qh:2", "sess", 1001) and not orl.verify(k, t, "qh:1", "other", 1001)
    assert not orl.verify(k, "junk", "qh:1", "sess", 1001) and not orl.verify(b"x" * 32, t, "qh:1", "sess", 1001)
