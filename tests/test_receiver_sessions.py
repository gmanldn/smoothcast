from receiver_sessions import Sessions


def test_sessions_are_isolated_with_distinct_tokens():
    s = Sessions()
    a, b = s.start("tv", "film.mkv"), s.start("kitchen", "song.flac")
    assert a.token != b.token and s.resolve(a.token).receiver == "tv"
    assert s.update("tv", a.token, state="playing", position=12.5)
    assert s.get("kitchen").state == "starting" and s.get("tv").position == 12.5


def test_failure_and_stop_do_not_leak_across_receivers():
    s = Sessions()
    a, b = s.start("tv", "x"), s.start("kitchen", "y")
    s.fail("tv", a.token, "encoder died")
    assert s.get("tv").state == "error" and s.get("kitchen").state == "starting"
    assert s.stop("tv") and s.get("kitchen") and s.get("tv") is None
    assert not s.stop("kitchen", "wrong-token") and s.get("kitchen")


def test_stale_token_cannot_act_on_replacement():
    s = Sessions()
    old = s.start("tv", "a")
    new = s.start("tv", "b")
    assert not s.update("tv", old.token, state="playing")
    assert s.resolve(old.token) is None and s.resolve(new.token).media == "b"


def test_cap_and_bad_state():
    s = Sessions(max_sessions=2)
    s.start("a", "m"); t = s.start("b", "m")
    assert s.start("c", "m") is None and s.start("a", "m2")
    assert not s.update("b", t.token, state="bogus")
    assert not s.update("b", t.token, token="x") or s.get("b").token == t.token
