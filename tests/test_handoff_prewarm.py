from handoff_prewarm import Prewarm


def test_start_window_and_missing_inputs():
    p = Prewarm()
    assert p.should_start(100, 70, "b")
    assert not p.should_start(100, 10, "b")      # too early
    assert not p.should_start(100, 97, "b")      # too late
    assert not p.should_start(100, 70, None)
    assert not p.should_start(float("nan"), 70, "b")


def test_result_roundtrip_and_no_duplicate_warm():
    p = Prewarm()
    t = p.begin("b", 0)
    assert not p.should_start(100, 70, "b")      # already in flight
    assert p.finish(t, {"v": 1})
    assert not p.should_start(100, 70, "b")      # already ready
    assert p.take("b", 10) == {"v": 1}
    assert p.take("b", 10) is None               # consumed


def test_stale_token_and_cancel_discard_results():
    p = Prewarm()
    old = p.begin("b", 0)
    new = p.begin("c", 1)
    assert not p.finish(old, "x") and p.finish(new, "y")
    p.cancel()
    assert p.take("c", 2) is None
    t = p.begin("d", 0)
    p.cancel()
    assert not p.finish(t, "z")


def test_wrong_item_or_expired_result_is_not_used():
    p = Prewarm()
    t = p.begin("b", 0)
    p.finish(t, "ok")
    assert p.take("other", 1) is None
    t = p.begin("b", 0)
    p.finish(t, "ok")
    assert p.take("b", 500) is None
