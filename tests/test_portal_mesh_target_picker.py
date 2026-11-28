from src.mesh_visibility import Seen, TargetEntry
from src import portal_target_picker as P


def ent(i, name, state="ready", age=100, owner="", node="n1"):
    return TargetEntry(id=i, name=name, kinds=("chromecast",), models=(), formats=(), seen_by=(Seen(node, state, age),), state=state, owner_hint=owner)


INV = [ent("t3", "Den", "busy", owner="bob"), ent("t1", "Lounge"), ent("t2", "Attic", "stale"), ent("t4", "Bed", age=60_000), ent("t5", "Zed", "unreachable")]


def test_ready_owned_targets_only_filters_stale_busy_foreign():
    assert [r["id"] for r in P.rows(INV, "me", ready_only=True)] == ["t1"]
    allrows = P.rows(INV, "me")
    assert [r["id"] for r in allrows] == ["t1", "t2", "t4", "t3", "t5"]    # ready first, then by name
    by = {r["id"]: r for r in allrows}
    assert by["t4"]["state"] == "unreachable" and by["t4"]["ready"] is False   # old ready hint is not trusted
    assert by["t3"]["reason"] == P.REASONS["foreign"] and by["t1"]["via"] == "n1"
    assert P.rows([ent("b", "Mine", "busy", owner="me")], "me")[0]["reason"] == P.REASONS["busy"]


def test_rows_expose_no_private_fields_and_are_bounded():
    r = P.rows(INV, "me")[0]
    assert set(r) == {"id", "name", "kind", "state", "ready", "reason", "via"}
    assert len(P.rows([ent(f"x{i}", f"n{i}") for i in range(200)])) == P.MAX_ROWS


def test_stable_target_id_during_live_updates():
    first = P.rows(INV)
    again = P.rows(list(reversed(INV)))
    assert P.merge_selection("t1", first)["selected"] == "t1" == P.merge_selection("t1", again)["selected"]


def test_disappeared_selection_is_not_auto_switched():
    m = P.merge_selection("t1", P.rows([ent("t9", "Other")]))
    assert m["selected"] is None and m["prompt"] == "Choose where to play" and "disappeared" in m["notice"]
    assert P.merge_selection(None, [])["prompt"] == "Choose where to play"


def test_revoked_duplicate_stale_selection():
    rows = P.rows(INV, "me")
    assert P.validate("t1", rows)[0] == 200 and P.validate("t1", rows)[1]["playing"] is False
    assert P.validate("nope", rows)[:2] == (409, {"error": "target_gone", "message": "That screen or speaker isn't available any more."})
    assert P.validate("t3", rows)[0] == 403 and P.validate("t2", rows)[0] == 503
    assert P.validate("", rows)[0] == 400 and P.validate(None, rows)[0] == 400
    assert P.validate(["t1"], rows)[0] == 400


def test_acceptance_distinct_from_playback_confirmation():
    assert P.status(True, "idle") == "Accepted — waiting for the screen to start"
    assert P.status(True, None).startswith("Accepted")
    assert P.status(True, "playing") == "Playing" and P.status(False, "playing") == "Choose where to play"


def test_conflicting_ready_and_foreign_busy_is_unavailable_both_orders():
    fresh_ready = Seen("n1", "ready", 0)
    fresh_busy = Seen("n2", "busy", 0)
    for seen_by in ((fresh_ready, fresh_busy), (fresh_busy, fresh_ready)):
        e = TargetEntry(id="t", name="Den", kinds=("chromecast",), models=(), formats=(),
                        seen_by=seen_by, state="ready", owner_hint="bob")
        row = P.rows([e], "me")[0]
        assert row["ready"] is False
        assert row["state"] == "busy"
        assert row["reason"] == P.REASONS["foreign"]
        assert row["via"] is None
    rows = P.rows([TargetEntry(id="t", name="Den", kinds=("chromecast",), models=(), formats=(),
                               seen_by=(fresh_ready, fresh_busy), state="ready", owner_hint="bob")], "me")
    assert P.validate("t", rows)[0] != 200


def test_expired_busy_then_fresh_ready_recovers():
    stale_busy = Seen("n2", "busy", 99999)
    fresh_ready = Seen("n1", "ready", 0)
    e = TargetEntry(id="t", name="Den", kinds=("chromecast",), models=(), formats=(),
                    seen_by=(stale_busy, fresh_ready), state="ready", owner_hint="bob")
    row = P.rows([e], "me")[0]
    assert row["ready"] is True
    assert row["state"] == "ready"
    assert row["reason"] == ""
    assert row["via"] == "n1"
