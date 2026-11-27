import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_crdt as q


def ref(n):
    return {"content_ref": f"qh:{n}", "added_by": "me", "added_at": 1}


def ids(r):
    return [i["id"] for i in q.ordered(r.state)]


def test_generate_key_is_strictly_between_for_random_pairs():
    rng = random.Random(1)
    keys = [None]
    for _ in range(300):
        a, b = sorted(rng.sample(keys, 2), key=lambda k: k or "") if len(keys) > 1 else (None, None)
        if a == b:
            a, b = None, None
        k = q.generate_key(a, b)
        assert (a or "") < k and (b is None or k < b) and not k.endswith("a"), (a, b, k)
        keys.append(k)


def test_convergence_three_replicas_200_seeds_random_interleavings():
    for seed in range(200):
        rng = random.Random(seed)
        reps = [q.Replica(n) for n in ("n1", "n2", "n3")]
        pool = []
        for step in range(25):
            r = rng.choice(reps)
            live = ids(r)
            c = rng.random()
            if c < .5 or not live:
                after = rng.choice(live + [None]); idx = live.index(after) + 1 if after in live else 0
                before = live[idx] if idx < len(live) else None
                pool += r.insert(f"{r.node}-{step}", ref(step), after, before)
            elif c < .8:
                tgt = rng.choice(live); rest = [x for x in live if x != tgt]
                after = rng.choice(rest + [None]); idx = rest.index(after) + 1 if after in rest else 0
                pool += r.move(tgt, after, rest[idx] if idx < len(rest) else None)
            else:
                pool += r.delete(rng.choice(live))
            if rng.random() < .3:                       # partial, shuffled, duplicated delivery
                o = rng.choice(reps); batch = rng.sample(pool, len(pool)); o.receive(batch[: len(batch) // 2])
        for r in reps:
            batch = pool + rng.sample(pool, len(pool) // 2); rng.shuffle(batch); r.receive(batch)
        assert ids(reps[0]) == ids(reps[1]) == ids(reps[2]), seed
        assert ids(reps[0]) == [i["id"] for i in q.ordered(q.merge(reps[0].state, reps[1].state))]


def test_partition_heal_keeps_every_insert():
    a, b = q.Replica("a"), q.Replica("b")
    base = a.insert("x", ref(0)) + a.insert("y", ref(1), after="x"); b.receive(base)
    ea = a.insert("a1", ref(2), after="x", before="y") + a.insert("a2", ref(3), after="a1", before="y")
    eb = b.insert("b1", ref(4), after="x", before="y") + b.insert("b2", ref(5), after="y")
    a.receive(eb); b.receive(ea)
    assert ids(a) == ids(b) and set(ids(a)) == {"x", "y", "a1", "a2", "b1", "b2"} and ids(a)[0] == "x" and ids(a)[-1] == "b2"


def test_concurrent_move_and_delete_delete_wins_either_order():
    a, b = q.Replica("a"), q.Replica("b")
    base = a.insert("x", ref(0)) + a.insert("y", ref(1), after="x"); b.receive(base)
    mv, dl = a.move("x", after="y"), b.delete("x")
    a.receive(dl); b.receive(mv)
    assert ids(a) == ids(b) == ["y"]
    c = q.Replica("c"); c.receive(mv + dl + base); d = q.Replica("d"); d.receive(base + dl + mv)
    assert ids(c) == ids(d) == ["y"]


def test_ops_idempotent_and_out_of_order_delivery():
    a = q.Replica("a"); ops = a.insert("x", ref(0)) + a.insert("y", ref(1), after="x") + a.move("x", after="y") + a.delete("y")
    b = q.Replica("b"); b.receive(ops[::-1]); b.receive(ops); b.receive(ops)
    assert ids(b) == ids(a) == ["x"]
    s = q.new_state()
    for o in ops: q.apply(s, o)
    before = {k: dict(v) for k, v in s["items"].items()}
    for o in ops: q.apply(s, o)
    assert s["items"] == before


def test_merge_commutative_associative_idempotent():
    a, b, c = q.Replica("a"), q.Replica("b"), q.Replica("c")
    a.insert("x", ref(0)); b.insert("y", ref(1)); c.insert("z", ref(2)); b.delete("y"); a.move("x", before=None)
    m = q.merge
    assert m(a.state, b.state) == m(b.state, a.state)
    assert m(m(a.state, b.state), c.state) == m(a.state, m(b.state, c.state))
    assert m(a.state, a.state)["items"] == a.state["items"]


def test_key_growth_bounded_by_rebalance():
    r = q.Replica("a"); r.insert("first", ref(0)); r.insert("last", ref(1), after="first")
    for i in range(120):
        r.insert(f"n{i}", ref(i), after="first", before=ids(r)[1])
    assert max(len(i["key"]) for i in q.ordered(r.state)) <= q.MAX_KEY + 1
    assert len(ids(r)) == 122 and ids(r)[0] == "first"


def test_invalid_ops_ignored_and_item_cap():
    s = q.new_state()
    for bad in [{}, {"op": "ins"}, {"op": "ins", "id": "../x", "key": "b", "ref": ref(1), "lamport": 1, "node": "n"},
                {"op": "mov", "id": "x", "key": "AB", "lamport": 1, "node": "n"}, {"op": "mov", "id": "x", "key": "ba", "lamport": 1, "node": "n"},
                {"op": "del", "id": "x", "lamport": True, "node": "n"}, {"op": "ins", "id": "x", "key": "b", "ref": {"content_ref": ""}, "lamport": 1, "node": "n"}]:
        q.apply(s, bad)
    assert s["items"] == {}
    for i in range(q.MAX_ITEMS + 20):
        q.apply(s, {"op": "ins", "id": f"i{i}", "key": "b", "ref": ref(i), "lamport": i, "node": "n"})
    assert len(s["items"]) == q.MAX_ITEMS
