import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import follow_me as fm

SNAP = {"media": "m", "rate": 1.0, "queue": ["a", "b"]}


def run(playing_after=3.0, timeout=False):
    h = fm.Handoff("h1", "lounge", "kitchen", SNAP, 0, source_name="Lounge", target_name="Kitchen")
    assert h.next_action(0)["queue"] == ["a", "b"]                        # queue travels
    assert h.prepared(1, 1000.0) == {"do": "start_target", "target": "kitchen", "position": 1000.0}
    h.started(2)
    stops = []
    for t in range(3, 40):
        pos = 1000 + (t - 1) if not timeout and t >= 2 + playing_after else 0
        act = h.target_status(playing=not timeout and t >= 2 + playing_after, position=pos, now=t)
        if act:
            stops.append((t, act))
            if act["do"] == "stop_source" or act.get("keep_source"):
                break
    return h, stops


def test_source_stopped_only_after_target_confirmed_and_position_within_2s():
    h, stops = run()
    assert h.state == fm.DONE and stops[0][1] == {"do": "stop_source", "source": "lounge"}
    assert h.actions.index("start_target") < h.actions.index("stop_source")
    assert abs(1000 + (stops[0][0] - 1) - h.expected_position(stops[0][0])) <= fm.MAX_DELTA_S


def test_timeout_rolls_back_and_never_stops_source():
    h, stops = run(timeout=True)
    assert h.state == fm.ROLLED_BACK and "stop_source" not in h.actions
    assert stops[-1][1]["keep_source"] and h.message == "Couldn't start in Kitchen; still playing in Lounge."
    assert h.fail("again") == {"do": "none"}


def test_wrong_position_does_not_count_as_confirmed():
    h = fm.Handoff("h", "a", "b", SNAP, 0); h.prepared(0, 500.0); h.started(0)
    assert h.target_status(True, 0.0, 1) is None and h.state == fm.CONFIRMING


def test_source_loss_continues_target_but_not_before_it_plays():
    h = fm.Handoff("h", "a", "b", SNAP, 0, target_name="Kitchen"); h.prepared(0, 5); h.started(0)
    assert h.source_lost(False) is None and h.state == fm.CONFIRMING
    assert h.source_lost(True)["message"] == "Moved to Kitchen." and h.state == fm.DONE


def test_idempotent_ids_and_busy_and_same_room():
    m = fm.Mover()
    h, why = m.begin("x", "a", "b", SNAP, 0); h2, why2 = m.begin("x", "a", "b", SNAP, 1)
    assert h2 is h and why2 == "duplicate"
    assert m.begin("y", "c", "b", SNAP, 1)[0] is None and m.begin("z", "q", "q", SNAP, 1)[1] == "Already playing there."


def test_automation_endpoint_rejects_unauthenticated_and_low_roles():
    assert not fm.authorised(False, "host") and not fm.authorised(True, "guest") and fm.authorised(True, "cohost")
