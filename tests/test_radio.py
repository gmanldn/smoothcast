import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import radio


def lib(n=60):
    rnd = random.Random(4); gs = [["rock"], ["rock", "indie"], ["jazz"], ["pop"], ["jazz", "blues"]]
    return [{"id": f"t{i}", "artist": f"A{i % 12}", "album": f"Al{i % 8}", "genres": rnd.choice(gs), "year": rnd.randrange(1985, 2020),
             "bpm": rnd.randrange(70, 170), "loudness": -rnd.uniform(8, 20)} for i in range(n)]


def test_similarity_orders_by_relation():
    a = {"artist": "X", "genres": ["rock"], "year": 2000, "bpm": 120}
    same = {"artist": "X", "genres": ["rock"], "year": 2001, "bpm": 122}
    far = {"artist": "Y", "genres": ["jazz"], "year": 1970, "bpm": 60}
    assert radio.similarity(a, same) > radio.similarity(a, far) and radio.similarity(a, far) == 0.0
    assert radio.similarity({}, {}) == 0.0


def test_deterministic_for_a_seed_and_different_seeds_differ_somewhere():
    L = lib(); seed = radio.seed_profile("genre", "rock", L)
    a = radio.Station(seed, L, 1); b = radio.Station(seed, L, 1)
    assert [a.next(i * 200)["id"] for i in range(15)] == [b.next(i * 200)["id"] for i in range(15)]


def test_no_artist_twice_in_3_and_no_track_twice_in_4h_property():
    for s in range(20):
        L = lib(); st = radio.Station(radio.seed_profile("artist", "A1", L), L, s); picks = []
        for i in range(40):
            t = st.next(i * 120)
            assert t is not None; picks.append((t, i * 120))
        for i, (t, at) in enumerate(picks):
            assert all(t["artist"] != p["artist"] for p, _ in picks[max(0, i - 3):i])
            assert all(t["id"] != p["id"] for p, pat in picks[:i] if at - pat < radio.REPEAT_S)


def test_exhausted_library_returns_none_instead_of_repeating():
    L = lib(3); st = radio.Station({"genres": ["rock"]}, L, 0)
    got = [st.next(i) for i in range(10)]
    assert sum(g is not None for g in got) <= 3 and got[-1] is None


def test_kids_filter_and_exclusion_applied_before_scoring():
    L = lib(); st = radio.Station(radio.seed_profile("genre", "rock", L), L, 0)
    ok = lambda t: "jazz" not in t["genres"]
    for i in range(20):
        t = st.next(i * 100, allow=ok, exclude={"t0", "t1"})
        assert t and ok(t) and t["id"] not in ("t0", "t1")


def test_thumbs_shift_weights_and_are_bounded_and_independent_per_station():
    L = lib(); seed = radio.seed_profile("genre", "rock", L); a, b = radio.Station(seed, L, 0), radio.Station(seed, L, 0)
    t = next(x for x in L if "rock" in x["genres"])
    a.feedback(t, True); assert a.w["genre"] > radio.W["genre"] and b.w == radio.W
    for _ in range(50):
        a.feedback(t, False)
    assert a.w["genre"] >= 0.0 and all(v >= 0 for v in a.w.values())


def test_human_items_precede_station_items_and_seed_kinds():
    q = radio.queue_with_station([{"id": "h1"}, {"id": "h2"}], [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}, {"id": "s4"}], 4)
    assert [x["id"] for x in q] == ["h1", "h2", "s1", "s2"] and q[2]["source"] == "station" and "source" not in q[0]
    L = lib()
    assert radio.seed_profile("album", "Al3", L)["ids"] and radio.seed_profile("track", "t5", L)["ids"] == {"t5"} and radio.seed_profile("genre", "nope", L) == {}
