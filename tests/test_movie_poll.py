import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import movie_poll as mp

OPTS = [{"id": x, "title": t} for x, t in (("a", "Paddington 2"), ("b", "Alien"), ("c", "Up"))]


def test_irv_table_including_transfers_and_exhausted_ballots():
    ids = ["a", "b", "c"]
    for ballots, win, votes, total in [([["a"], ["a"], ["b"]], "a", 2, 3), ([["c"]], "c", 1, 1), ([["b", "x", "b"]], "b", 1, 1)]:
        r = mp.irv(ballots, ids); assert (r["winner"], r["votes"], r["total"]) == (win, votes, total), ballots
    r = mp.irv([["a", "b"], ["b", "a"], ["c", "b"], ["c", "b"], ["b", "c"]], ids)    # a(1) out; its vote moves to b -> b 3 of 5
    assert r["winner"] == "b" and r["rounds"][0] == {"a": 1, "b": 2, "c": 2} and r["rounds"][-1]["b"] == 3 and r["total"] == 5
    ex = mp.irv([["a"], ["b", "a"], ["b"], ["c"]], ids)                          # c and a tie low; one eliminated with a seeded draw
    assert (ex["winner"], ex["votes"], ex["total"], ex["tie_broken"]) == ("b", 2, 3, True)
    assert mp.irv([], ids)["winner"] is None and mp.irv([[], ["zzz"]], ids)["winner"] is None


def test_ties_fewest_seen_then_seeded_random_reproducible():
    ids = ["a", "b"]; ballots = [["a"], ["b"]]
    assert mp.irv(ballots, ids, {"a": 3, "b": 1})["winner"] == "b" and mp.irv(ballots, ids, {"a": 0, "b": 2})["winner"] == "a"
    assert mp.irv(ballots, ids, {"a": 3, "b": 1})["tie_broken"] is True
    outs = {s: mp.irv(ballots, ids, seed=s)["winner"] for s in range(30)}
    assert {"a", "b"} <= set(outs.values()) and all(mp.irv(ballots, ids, seed=s)["winner"] == w for s, w in outs.items())
    assert mp.irv(ballots, ids, seed=7)["seed"] == 7


def test_only_present_at_close_count_and_early_close_and_timer_clamp():
    p = mp.Poll(OPTS, ["sam", "mum", "kid"], now=0, seconds=5); assert p.closes_at == 30
    assert mp.Poll(OPTS, ["x"], 0, 999).closes_at == 180
    assert p.vote("sam", ["a"], 1) and p.vote("mum", ["b"], 1) and not p.due(2)
    assert not p.vote("stranger", ["a"], 1) and not p.vote("sam", ["zzz"], 1)
    p.vote("kid", ["b"], 2); assert p.due(2)                                    # everyone present has voted
    p.leave("kid"); r = p.close(3)                                              # kid left: ballot dropped; a vs b tie
    assert r["total"] == 2 and r["tie_broken"] and r["tie_note"].startswith("Tie broken with seed")
    q = mp.Poll(OPTS, ["sam", "mum"], 0); q.vote("sam", ["a"], 1); assert not q.due(59.9) and q.due(60) and not q.vote("mum", ["a"], 61)
    q.join("late"); assert not q.due(10)                                          # newcomer must vote too


def test_result_copy_countdown_cancel_and_nobody_voted():
    p = mp.Poll(OPTS, list("12345"), 0)
    for w, c in zip("12345", "aaabb"):
        p.vote(w, [c], 1)
    r = p.close(10); assert r["message"] == "'Paddington 2' wins (3 of 5 votes). Starting in 5…" and r["tie_note"] == ""
    assert p.should_start(14.9) is None and p.should_start(15) == "a" and p.close(99) is r
    p.cancel(); assert p.should_start(20) is None
    n = mp.Poll(OPTS, ["1", "2"], 0); r = n.close(60); assert r["message"] == "Nobody voted." and not r["start"] and n.should_start(100) is None


def test_ranked_mode_and_single_mode_truncation():
    s = mp.Poll(OPTS, ["1"], 0); s.vote("1", ["c", "a"], 1); assert s.ballots["1"] == ["c"]
    r = mp.Poll(OPTS, ["1", "2", "3"], 0, ranked=True)
    r.vote("1", ["a", "b"], 1); r.vote("2", ["b", "a"], 1); r.vote("3", ["c", "b"], 1)
    assert r.close(2)["winner"] == "b"                                           # c out, transfers to b


def test_suggest_excludes_seen_and_above_kids_limits_and_is_seeded():
    cands = [{"id": "g", "title": "G film", "ratings": ["G"]}, {"id": "pg", "title": "PG", "ratings": ["PG"]}, {"id": "r", "title": "R", "ratings": ["18"]},
             {"id": "seen", "title": "Seen", "ratings": ["G"]}, {"id": "unrated", "title": "?", "ratings": []}]
    present = [{"id": "dad", "seen": {"seen"}}, {"id": "kid", "kid": True, "limits": {"max_rating": "PG"}, "seen": set()}]
    out = {c["id"] for c in mp.suggest(cands, present, 10)}
    assert out == {"g", "pg"}                                                    # seen, 18 and unrated (blocked for kid) removed
    assert {c["id"] for c in mp.suggest(cands, [{"id": "dad", "seen": set()}], 10)} == {"g", "pg", "r", "seen", "unrated"}
    assert len(mp.suggest(cands, [], 4)) == 4 and mp.suggest(cands, [], 3, seed=2) == mp.suggest(cands, [], 3, seed=2)
