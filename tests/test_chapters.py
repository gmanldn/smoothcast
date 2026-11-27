import chapters as ch

PROBE = {"chapters": [
    {"start_time": "60.0", "end_time": "120.0", "tags": {"title": "Act II"}},
    {"start_time": "0", "end_time": "60.0", "tags": {}},
    {"start_time": "5", "end_time": "5"},
    {"start_time": "x", "end_time": "9"},
    "junk",
    {"start_time": "120", "end_time": "999", "tags": {"title": " Credits "}},
]}


def test_parse_sorts_drops_bad_and_names_untitled():
    got = ch.parse(PROBE, duration=150)
    assert [(c.start, c.title) for c in got] == [(0.0, "Chapter 1"), (60.0, "Act II"), (120.0, "Credits")]
    assert got[-1].end == 150


def test_parse_survives_garbage():
    assert ch.parse(None) == [] and ch.parse({"chapters": 3}) == []


def test_current_and_boundaries():
    got = ch.parse(PROBE)
    assert ch.current(got, 0).index == 0
    assert ch.current(got, 60).title == "Act II"
    assert ch.current(got, float("nan")) is None
    assert ch.current([], 5) is None


def test_jump_next_previous_and_restart():
    got = ch.parse(PROBE)
    assert ch.jump(got, 10, 1) == 60
    assert ch.jump(got, 130, 1) is None
    assert ch.jump(got, 70, -1) == 60       # >3s in: restart current
    assert ch.jump(got, 61, -1) == 0        # just started: go back
    assert ch.jump(got, 0, -1) is None
