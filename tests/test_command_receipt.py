import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import command_receipt as cr


def mk():
    r = cr.Receipts()
    return r, lambda rid, a, arg=None, **k: r.issue(rid, a, arg, 1, "m1", 0, **k)


def test_202_alone_is_only_accepted_and_confirms_on_postcondition():
    r, issue = mk(); issue("a", "pause")
    assert r.get("a")["status"] == cr.ACCEPTED
    r.observe({"state": "PLAYING"}, 1, "m1", 1)
    assert r.get("a")["status"] == cr.EXECUTING
    r.observe({"state": "PAUSED"}, 1, "m1", 2)
    assert r.get("a")["status"] == cr.CONFIRMED


def test_timeout_is_uncertain_not_a_spinner():
    r, issue = mk(); issue("a", "play")
    r.observe({"state": "PAUSED"}, 1, "m1", cr.DEADLINE_S + 1)
    assert r.get("a")["status"] == cr.UNCERTAIN and r.get("a")["retry_ok"]


def test_wrong_media_fails_and_old_generation_never_confirms_later():
    r, issue = mk(); issue("a", "stop")
    r.observe({"state": "PAUSED"}, 1, "other", 1)
    assert r.get("a")["status"] == cr.FAILED
    issue("b", "pause")
    r.supersede(2)
    assert r.get("b")["status"] == cr.UNCERTAIN
    r.observe({"state": "PAUSED"}, 2, "m1", 3)
    assert r.get("b")["status"] == cr.UNCERTAIN


def test_seek_volume_tolerance_rejections_and_bounds():
    r, issue = mk(); issue("s", "seek", 100); issue("v", "volume", 0.5); issue("x", "play", accepted=False)
    r.observe({"state": "PLAYING", "position": 101.5, "volume": 0.51}, 1, "m1", 1)
    assert r.get("s")["status"] == r.get("v")["status"] == cr.CONFIRMED
    assert r.get("x")["status"] == cr.REJECTED
    for i in range(cr.MAX_RECEIPTS + 5):
        issue(f"n{i}", "play")
    assert len(r._r) == cr.MAX_RECEIPTS
