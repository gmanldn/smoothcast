import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_media_ids as nm


def mk():
    s = nm.SharedMedia(b"k"); s.share("film1", "/media/film1.mkv"); return s


def test_issue_and_resolve_for_the_right_peer_only():
    s = mk(); mid = s.issue("film1", "B", 0)
    assert "/media" not in mid and s.resolve(mid, "B", 10) == ("/media/film1.mkv", "")
    assert s.resolve(mid, "C", 10)[0] is None


def test_expiry_unshare_revoke_and_tamper():
    s = mk(); mid = s.issue("film1", "B", 0, ttl=60)
    assert "expired" in s.resolve(mid, "B", 61)[1]
    bad = mid[:-1] + ("0" if mid[-1] != "0" else "1")
    assert s.resolve(bad, "B", 1)[0] is None and s.resolve("junk", "B", 1)[0] is None
    s.unshare("film1"); assert "no longer shared" in s.resolve(mid, "B", 1)[1]
    s.share("film1", "/m"); s.revoke_peer("B")
    assert s.resolve(mid, "B", 1)[0] is None and s.issue("film1", "B", 0) is None


def test_unshared_items_get_no_id_and_ttl_is_bounded():
    s = mk()
    assert s.issue("secret", "B", 0) is None
    far = s.issue("film1", "B", 0, ttl=10**9)
    assert int(far.split(".")[1]) == 24 * 3600
