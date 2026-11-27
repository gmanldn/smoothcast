import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import participant_panel as pp


def test_rows_show_name_role_age_and_protect_host():
    r = pp.rows([{"id": "1", "name": " Sam ", "role": "controller", "last_seen": 95},
                 {"id": "2", "name": "", "role": "weird", "last_seen": 0},
                 {"id": "3", "name": "Me", "role": "host", "last_seen": 99}], 100)
    by = {x["id"]: x for x in r}
    assert by["1"]["name"] == "Sam" and by["1"]["activity"] == "just now" and by["1"]["online"]
    assert by["2"]["name"] == "Guest" and by["2"]["role"] == "viewer" and not by["2"]["online"]
    assert by["2"]["activity"] == "1 min ago" and not by["3"]["can_change"]
    assert r[-1]["id"] == "2"                      # offline sorts last


def test_empty_state_is_helpful():
    assert "Share the room link" in pp.empty_message([]) and pp.empty_message([{}]) == ""


def test_policy_persists_atomically_and_never_defaults_to_host(tmp_path):
    f = tmp_path / "sub" / "policy.json"
    p = pp.Policy(f)
    assert p.role_for_new_guest() == "viewer" and not p.set_default_role("host")
    assert p.set_default_role("controller"); p.set_locked(True)
    q = pp.Policy(f)
    assert q.default_role == "controller" and q.locked and q.role_for_new_guest() is None
    assert [x.name for x in f.parent.iterdir()] == ["policy.json"]


def test_corrupt_policy_falls_back_to_safe_defaults(tmp_path):
    f = tmp_path / "p.json"; f.write_text("{nope")
    assert pp.Policy(f).default_role == "viewer"
