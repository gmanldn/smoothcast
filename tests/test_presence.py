import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import presence as p


def mk(path=None):
    t = [1000.0]; return p.Presence(path, lambda: t[0]), t


def test_opt_in_respected_default_off_and_ping_refused_when_off():
    pr, t = mk(); assert p.SETTING == "Count me as home when my phone is on the Wi-Fi"
    assert pr.ping("sam") == {"ok": False, "error": "Presence is off for this person."} and pr.home("sam") is False
    pr.set_opt_in("sam", True); assert pr.ping("sam") == {"ok": True, "next_ping_s": 600.0} and pr.home("sam")
    pr.set_opt_in("sam", False); assert pr.home("sam") is False and pr.ping("sam")["ok"] is False and pr.d["sam"]["last_seen"] is None


def test_expiry_with_fake_clock_and_ping_throttle():
    pr, t = mk(); pr.set_opt_in("sam", True); pr.ping("sam")
    t[0] += 1499; assert pr.home("sam"); t[0] += 2; assert not pr.home("sam")
    assert pr.ping("sam")["ok"] and pr.home("sam")
    t[0] += 10; assert pr.ping("sam") == {"ok": True, "throttled": True}
    t[0] += 300; assert pr.ping("sam") == {"ok": True, "next_ping_s": 600.0}


def test_no_history_persisted_only_opt_in_and_last_seen(tmp_path):
    f = tmp_path / "presence.json"; pr, t = mk(f); pr.set_opt_in("sam", True)
    for _ in range(5): pr.ping("sam"); t[0] += 700
    d = json.loads(f.read_text())
    assert d == {"version": 1, "residents": {"sam": {"opt_in": True, "last_seen": 1000.0 + 4 * 700}}}
    assert len(f.read_text()) < 120 and sorted(d["residents"]["sam"]) == ["last_seen", "opt_in"]
    pr.set_opt_in("sam", False); assert json.loads(f.read_text())["residents"]["sam"] == {"opt_in": False, "last_seen": None}


def test_listing_is_residents_only_and_hides_opted_out_people():
    pr, t = mk(); pr.set_opt_in("sam", True); pr.set_opt_in("kim", True); pr.ping("sam")
    res = ["sam", "kim", "lee"]
    assert pr.listing("sam", res) == [{"resident_id": "sam", "home": True}, {"resident_id": "kim", "home": False}]
    assert pr.listing(None, res) is None and pr.listing("guest", res) is None and pr.at_home(res) == ["sam"]


def test_persistence_corruption_forget_and_bounds(tmp_path):
    f = tmp_path / "p.json"; pr, t = mk(f); pr.set_opt_in("sam", True); pr.ping("sam")
    assert p.Presence(f, lambda: 1000.0).home("sam"); pr.forget("sam"); assert "sam" not in json.loads(f.read_text())["residents"]
    f.write_text("{bad"); assert p.Presence(f).d == {}
    f.write_text(json.dumps({"residents": {"../x": {"opt_in": True}, "ok": {"opt_in": "yes", "last_seen": "now"}}})); q = p.Presence(f)
    assert list(q.d) == ["ok"] and q.d["ok"] == {"opt_in": False, "last_seen": None}
    for bad in ("", "a/b", None, "x" * 41): assert pr.set_opt_in(bad, True) is False
    for i in range(p.MAX_RESIDENTS): pr.set_opt_in(f"r{i}", True)
    assert pr.set_opt_in("one-too-many", True) is False
