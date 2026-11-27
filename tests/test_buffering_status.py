import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import buffering_status as bs


def F(**k):
    return {"receiver_state": "PLAYING", "receiver_seen_at": 100, **k}


def test_stall_sequence_buffering_recovering_playing_only_when_verified():
    assert bs.project(F(receiver_state="BUFFERING", buffer_ahead_s=1.234), 101)["phase"] == "buffering"
    r = bs.project(F(recovering=True), 101)
    assert r["phase"] == "recovering" and "seek" in r["blocked"]
    p = bs.project(F(), 101)
    assert p["phase"] == "playing" and p["blocked"] == []


def test_stale_or_missing_data_is_unknown_without_invented_numbers():
    u = bs.project({"buffer_ahead_s": 9}, 100)
    assert u["phase"] == "unknown" and u["buffer_ahead_s"] is None and u["message"] == "State unknown"
    assert bs.project(F(), 200)["phase"] == "unknown"


def test_offline_is_not_completion_and_never_advances_queue():
    o = bs.project(F(had_session=True), 200)
    assert o["phase"] == "offline" and not o["advance_queue"]
    assert bs.project(F(offline=True), 101)["phase"] == "offline"
    s = bs.project(F(receiver_state="IDLE", ended_normally=True), 101)
    assert s["phase"] == "stopped" and s["advance_queue"]
    assert not bs.project(F(receiver_state="IDLE"), 101)["advance_queue"]


def test_toasts_bounded_per_episode_and_reset_on_playing():
    n = bs.Notifier()
    assert [n.should_toast("recovering") for _ in range(4)] == [True, True, False, False]
    assert not n.should_toast("playing") and n.should_toast("buffering")
