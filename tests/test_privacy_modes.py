import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import privacy_modes as pm

SNAP = {"state": "PLAYING", "pin": "4821", "token": "sekret-token",
        "now": {"id": "q1", "title": "Holiday.mkv", "path": "/home/alice/Videos/Holiday.mkv",
                "src": "http://bob:hunter2@nas/x.mp4", "note": "see /home/alice/x"},
        "queue": [{"id": "q2", "title": "Private", "folder": "/mnt/secret"}],
        "history": ["/home/alice/old.mkv"], "owner": "alice-laptop"}
CANARIES = ["sekret-token", "4821", "hunter2", "/home/alice", "/mnt/secret", "old.mkv"]


def test_guest_payload_has_no_canaries_at_any_level():
    for level in ("full", "hidden", "bogus"):
        for role in ("viewer", "controller"):
            text = json.dumps(pm.redact(SNAP, role, level, user="alice"))
            assert pm.leaks(text, CANARIES) == [], (role, level)


def test_hidden_level_masks_titles_but_keeps_stable_ids():
    out = pm.redact(SNAP, "viewer", "hidden", "alice")
    assert out["now"]["title"] == pm.HIDDEN_TITLE and out["now"]["id"] == "q1"
    assert out["queue"][0]["id"] == "q2" and out["state"] == "PLAYING"
    assert "alice" not in out["owner"] or "[user]" in out["owner"]


def test_full_level_keeps_titles_and_host_sees_everything_unchanged():
    assert pm.redact(SNAP, "viewer", "full", "alice")["now"]["title"] == "Holiday.mkv"
    assert pm.redact(SNAP, "host", "hidden") is SNAP
    assert SNAP["pin"] == "4821"                 # input never mutated
