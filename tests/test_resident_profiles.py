import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import resident_profiles as rp


def test_crud_persists_and_public_view_hides_pin(tmp_path):
    f = tmp_path / "residents.json"
    r = rp.Residents(f); a = r.add("Sam", kid=True); r.set_pin(a, "4821")
    b = r.add("Mum")
    again = rp.Residents(f)
    assert [x["name"] for x in again.public()] == ["Mum", "Sam"]
    pub = json.dumps(again.public())
    assert "4821" not in pub and "hash" not in pub and again.public()[1]["has_pin"] and again.public()[1]["kid"]
    assert "4821" not in f.read_text() and json.loads(f.read_text())["version"] == 1
    assert again.rename(b, "Mom") and again.delete(b) and not again.delete(b)
    assert [p.name for p in tmp_path.iterdir()] == ["residents.json"]


def test_pin_rules_verify_and_lockout(tmp_path):
    r = rp.Residents(tmp_path / "r.json"); a = r.add("Sam")
    assert r.verify(a, None, 0) == (True, "")                       # no PIN set
    assert not r.set_pin(a, "12") and not r.set_pin(a, "abcd") and r.set_pin(a, "123456")
    assert r.verify(a, "123456", 0) == (True, "")
    assert r.verify(a, "000000", 1)[1] == "That PIN didn't match. Try again."
    for t in range(rp.MAX_FAILS):
        r.verify(a, "000000", 2 + t)
    assert "Too many" in r.verify(a, "123456", 10)[1]
    assert r.verify(a, "123456", 10 + rp.LOCK_S + 10)[0]
    assert r.set_pin(a, None) and r.verify(a, None, 0)[0]


def test_names_unique_bounded_and_corrupt_file_ignored(tmp_path):
    r = rp.Residents(tmp_path / "r.json")
    assert r.add("Sam") and r.add("sam") is None and r.add("  ") is None
    for i in range(20):
        r.add(f"P{i}")
    assert len(r.items) == rp.MAX_RESIDENTS
    (tmp_path / "bad.json").write_text("{nope")
    assert rp.Residents(tmp_path / "bad.json").items == {}
