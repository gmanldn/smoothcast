import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_votes as qv


def test_replayed_vote_counts_once_and_unvote_removes():
    v = qv.Votes()
    for _ in range(3):
        assert v.vote("a", "u1")
    assert v.count("a") == 1 and v.voted("a", "u1")
    v.vote("a", "u1", False)
    assert v.count("a") == 0


def test_revoked_or_invalid_voters_are_rejected_and_not_counted():
    v = qv.Votes()
    assert not v.vote("a", "gone", active={"u1"}) and not v.vote("", "u1") and not v.vote("a", "")
    v.vote("a", "u1"); v.vote("a", "u2")
    assert v.count("a", active={"u1"}) == 1


def test_order_never_moves_playing_or_pinned_and_ties_keep_order():
    v = qv.Votes()
    q = ["now", "a", "b", "c", "d"]
    for u in ("u1", "u2", "u3"):
        v.vote("d", u)
    v.vote("c", "u1")
    assert v.order(q, playing_id="now") == ["now", "d", "c", "a", "b"]
    assert v.order(q, playing_id="now", pinned={"a"}) == ["now", "a", "d", "c", "b"]
    assert qv.Votes().order(q, "now") == q


def test_bounds_and_forget():
    v = qv.Votes()
    for i in range(qv.MAX_VOTERS_PER_ITEM):
        assert v.vote("a", f"u{i}")
    assert not v.vote("a", "extra")
    v.forget(set())
    assert v.count("a") == 0
