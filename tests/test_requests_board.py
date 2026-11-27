import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import requests_board as rb


def mk(tmp_path=None):
    t = [0.0]
    return rb.Board(tmp_path / "r.json" if tmp_path else None, clock=lambda: t[0]), t


def test_add_listing_empty_copy_and_duplicate_plus_one():
    b, _ = mk(); assert b.listing() == {"requests": [], "empty": "No requests yet. Ask for something you'd like to watch or hear."}
    a = b.add("Paddington 2", "sam", False); assert a["ok"] and not a["duplicate"]
    d = b.add("  paddington   2!! ", "mum", True); assert d["duplicate"] and d["id"] == a["id"] and d["votes"] == 2 and "+1" in d["message"]
    assert b.add("PADDINGTON 2", "mum", True)["votes"] == 2                       # same person can't +1 twice
    assert b.add("Paddíngton 2", "kid", True)["duplicate"]                         # accents fold
    assert b.listing()["requests"][0]["votes"] == 3 and b.listing()["empty"] == ""
    assert not b.add("   ", "sam", False)["ok"] and not b.add("!!!", "sam", False)["ok"] and not b.add(None, "sam", False)["ok"]


def test_cap_of_100_open_requests():
    b, _ = mk()
    for i in range(100):
        assert b.add(f"film {i}", "sam", False)["ok"]
    assert b.add("one more", "sam", False) == {"ok": False, "message": "The request board is full for now."}
    assert b.add("film 5", "x", False)["duplicate"]                                # +1 still works when full


def test_guest_requests_expire_after_14_days_residents_do_not():
    b, t = mk(); b.add("guest film", "g", True); b.add("resident film", "r", False)
    t[0] = rb.GUEST_TTL_S - 1; assert len(b.listing()["requests"]) == 2
    t[0] = rb.GUEST_TTL_S + 1; assert [r["text"] for r in b.listing()["requests"]] == ["resident film"]


def test_delete_permissions_and_fulfil_notifies_all_voters_including_returning_guest():
    b, t = mk(); r = b.add("Paddington 2", "guest1", True)["id"]; b.add("paddington 2", "sam", False)
    assert not b.delete(r, "stranger", host=False) and b.delete(r, "guest1", host=False) is True
    r = b.add("Album X", "guest1", True)["id"]; assert b.delete(r, "other", host=True)
    r = b.add("Paddington 2", "guest1", True)["id"]; b.add("paddington 2", "sam", False)
    assert not b.fulfil(r, "Paddington 2", host=False) and b.fulfil(r, "Paddington 2") and not b.fulfil(r, "x")
    t[0] = 5 * 86400                                                               # guest returns days later
    assert b.notifications("guest1") == ["Your request 'Paddington 2' is ready to watch."] and b.notifications("guest1") == []
    assert b.notifications("sam") == ["Your request 'Paddington 2' is ready to watch."] and b.listing()["requests"] == []


def test_notification_dropped_when_guest_never_returns():
    b, t = mk(); r = b.add("x film", "g", True)["id"]; b.fulfil(r, "x")
    t[0] = rb.NOTE_TTL_S + 1; assert b.notifications("g") == []


def test_persistence_and_corrupt_file(tmp_path):
    b, t = mk(tmp_path); b.add("Persist me", "sam", False); rid = b.listing()["requests"][0]["id"]
    b2 = rb.Board(tmp_path / "r.json", clock=lambda: 1.0); assert b2.listing()["requests"][0]["id"] == rid
    (tmp_path / "bad.json").write_text("{nope"); assert rb.Board(tmp_path / "bad.json").listing()["requests"] == []
    (tmp_path / "bad2.json").write_text("[1,2]"); assert rb.Board(tmp_path / "bad2.json").listing()["requests"] == []


def test_sanitise_fuzz_printable_capped_and_never_raises():
    rnd = random.Random(9); alphabet = string.printable + "\x00\x1b‮​é\U0001f600"
    for _ in range(500):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randrange(0, 300)))
        out = rb.sanitise(s)
        assert len(out) <= rb.MAX_TEXT and all(c.isprintable() for c in out) and out == out.strip() and "  " not in out
        rb.norm(s)
    assert rb.sanitise(123) == "" and rb.sanitise("a‮b\x00c") == "abc"
