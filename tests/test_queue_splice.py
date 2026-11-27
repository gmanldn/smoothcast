import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_splice as s


def test_single_edits_are_minimal_splices():
    base = list("abcdefgh")
    assert s.splice_ops(base, base) == [] and s.splice_ops([], []) == []
    assert s.splice_ops(base, base + ["z"]) == [(8, 0, ["z"])]
    assert s.splice_ops(base, ["z"] + base) == [(0, 0, ["z"])]
    assert s.splice_ops(base, base[:3] + base[4:]) == [(3, 1, [])]
    assert s.splice_ops(base, base[:3] + ["z"] + base[3:]) == [(3, 0, ["z"])]
    assert s.splice_ops(base, base[:3] + ["z"] + base[4:]) == [(3, 1, ["z"])]
    assert s.splice_ops(base, []) == [(0, 8, [])] and s.splice_ops([], ["a", "b"]) == [(0, 0, ["a", "b"])]


def test_single_move_is_two_one_row_splices_up_and_down():
    base = list("abcdefgh")
    down = list("bcdeafgh"); up = list("abfcdegh"); swap = list("abdcefgh")
    assert s.splice_ops(base, down) == [(0, 1, []), (4, 0, ["a"])] and s.touched(s.splice_ops(base, down)) == 2
    assert s.splice_ops(base, up) == [(5, 1, []), (2, 0, ["f"])]
    for new in (down, up, swap): assert s.apply_ops(base, s.splice_ops(base, new)) == new
    assert s.touched(s.splice_ops(list(range(5000)), [1] + [0] + list(range(2, 5000)))) <= 2


def test_random_edits_always_reproduce_target_and_never_exceed_changed_span():
    rng = random.Random(7)
    for _ in range(500):
        old = [rng.randrange(30) for _ in range(rng.randrange(0, 40))]
        new = list(old)
        for _ in range(rng.randrange(0, 4)):
            c = rng.random()
            if c < .3: new.insert(rng.randrange(len(new) + 1), rng.randrange(30))
            elif c < .6 and new: del new[rng.randrange(len(new))]
            elif new:
                i = rng.randrange(len(new)); v = new.pop(i); new.insert(rng.randrange(len(new) + 1), v)
        ops = s.splice_ops(old, new)
        assert s.apply_ops(old, ops) == new
        assert s.touched(ops) <= len(old) + len(new)


def test_large_queue_single_edit_touches_one_row_and_is_fast():
    old = [f"k{i}" for i in range(5000)]
    t = time.perf_counter()
    r = s.splice_ops(old, old[:2500] + old[2501:]); a = s.splice_ops(old, old + ["x"]); m = s.splice_ops(old, old[1:2] + old[:1] + old[2:])
    dt = time.perf_counter() - t
    assert r == [(2500, 1, [])] and a == [(5000, 0, ["x"])] and s.touched(m) <= 2 and s.apply_ops(old, m) == old[1:2] + old[:1] + old[2:]
    assert dt < 0.1, dt


def test_duplicate_keys_and_messy_reorder_fall_back_to_one_bounded_splice():
    assert s.apply_ops(list("aabb"), s.splice_ops(list("aabb"), list("bbaa"))) == list("bbaa")
    old, new = list("abcdefgh"), list("hgfedcba")
    ops = s.splice_ops(old, new); assert len(ops) == 1 and s.apply_ops(old, ops) == new
    keep = list("xabcdey"); shuffled = list("xdbeacy"); ops = s.splice_ops(keep, shuffled)
    assert ops[0][0] == 1 and s.touched(ops) <= 10 and s.apply_ops(keep, ops) == shuffled
