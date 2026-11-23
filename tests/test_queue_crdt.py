"""#421: the mergeable queue converges for any delivery order."""
from __future__ import annotations

from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_crdt as qc


def order(replica):
    return [(i.id, i.key) for i in replica.ordered()]


def test_key_between_is_strictly_between_and_never_ends_in_zero():
    rng = random.Random(1)
    keys = [None]
    for _ in range(400):
        keys_sorted = sorted(k for k in keys if k)
        i = rng.randrange(len(keys_sorted) + 1)
        before = keys_sorted[i - 1] if i else None
        after = keys_sorted[i] if i < len(keys_sorted) else None
        key = qc.key_between(before, after)
        assert (before is None or before < key) and (after is None or key < after)
        assert not key.endswith("0")
        keys.append(key)
    with pytest.raises(ValueError):
        qc.key_between("b", "a")


def test_local_edits_build_the_expected_order():
    q = qc.QueueCrdt("a")
    one = q.insert("one")
    two = q.insert("two")                               # appended
    zero = q.insert("zero", before_id=one["id"])        # at the front
    mid = q.insert("mid", after_id=one["id"])           # between one and two
    assert [i.ref for i in q.ordered()] == ["zero", "one", "mid", "two"]
    q.move(two["id"], before_id=zero["id"])
    assert [i.ref for i in q.ordered()][0] == "two"
    q.delete(mid["id"])
    assert [i.ref for i in q.ordered()] == ["two", "zero", "one"]


@pytest.mark.parametrize("seed", range(200))
def test_replicas_converge_for_any_delivery_order_with_duplicates(seed):
    rng = random.Random(seed)
    replicas = [qc.QueueCrdt(n) for n in "abc"]
    log = []                                            # (origin index, op)
    for _ in range(rng.randint(8, 30)):
        idx = rng.randrange(3)
        r = replicas[idx]
        live = r.ordered()
        action = rng.choice(["ins", "ins", "mov", "del"]) if live else "ins"
        if action == "ins":
            anchor = rng.choice(live) if live and rng.random() < 0.6 else None
            where = rng.choice(["after_id", "before_id"])
            op = r.insert(f"t{len(log)}", **({where: anchor.id} if anchor else {}))
        elif action == "mov":
            target = rng.choice(live)
            others = [i for i in live if i.id != target.id]
            anchor = rng.choice(others) if others else None
            op = r.move(target.id, **({rng.choice(["after_id", "before_id"]): anchor.id} if anchor else {}))
        else:
            op = r.delete(rng.choice(live).id)
        log.append((idx, op))
        if rng.random() < 0.3:                          # sometimes sync a random pair mid-way
            a, b = rng.sample(range(3), 2)
            for _o, op2 in rng.sample(log, len(log)):
                replicas[b].apply(op2)
    for target in range(3):                             # finally everyone receives everything,
        deliveries = [op for _i, op in log] * rng.randint(1, 2)   # shuffled, possibly twice
        rng.shuffle(deliveries)
        for op in deliveries:
            replicas[target].apply(op)
    assert order(replicas[0]) == order(replicas[1]) == order(replicas[2]), f"seed {seed}"


def test_partition_then_heal_loses_no_inserts():
    a, b = qc.QueueCrdt("a"), qc.QueueCrdt("b")
    seed_ops = [a.insert("one"), a.insert("two"), a.insert("three")]
    for op in seed_ops:
        b.apply(op)
    side_a = [a.insert(f"a{i}") for i in range(5)] + [a.delete(seed_ops[0]["id"])]
    side_b = [b.insert(f"b{i}", after_id=seed_ops[1]["id"]) for i in range(5)] + [
        b.move(seed_ops[2]["id"], before_id=seed_ops[1]["id"])]
    for op in side_b:
        a.apply(op)
    for op in side_a:
        b.apply(op)
    assert order(a) == order(b)
    refs = [i.ref for i in a.ordered()]
    assert {f"a{i}" for i in range(5)} | {f"b{i}" for i in range(5)} <= set(refs)
    assert "one" not in refs and len(refs) == 12        # 13 items minus the deleted one


def test_operations_that_arrive_before_their_insert_are_held():
    origin = qc.QueueCrdt("a")
    ins = origin.insert("x")
    mov = origin.insert("y")
    move = origin.move(ins["id"], after_id=mov["id"])
    gone = origin.delete(mov["id"])
    late = qc.QueueCrdt("b")
    for op in (gone, move, mov, ins):                    # worst order: dependents first
        late.apply(op)
    assert order(late) == order(origin)


def test_delete_wins_over_a_concurrent_move_and_replays_are_idempotent():
    a, b = qc.QueueCrdt("a"), qc.QueueCrdt("b")
    ins = a.insert("x")
    other = a.insert("y")
    b.apply(ins), b.apply(other)
    moved = b.move(ins["id"], after_id=other["id"])
    deleted = a.delete(ins["id"])
    for op in (moved, deleted, moved, deleted):
        a.apply(op)
    for op in (deleted, moved, deleted):
        b.apply(op)
    assert order(a) == order(b) and [i.ref for i in a.ordered()] == ["y"]
    assert a.apply(deleted) is False and a.apply(moved) is False


def test_concurrent_inserts_at_the_same_spot_are_both_kept_in_a_stable_order():
    a, b = qc.QueueCrdt("a"), qc.QueueCrdt("b")
    first = a.insert("first")
    b.apply(first)
    x, y = a.insert("x", after_id=first["id"]), b.insert("y", after_id=first["id"])
    a.apply(y), b.apply(x)
    assert order(a) == order(b) and {i.ref for i in a.ordered()} == {"first", "x", "y"}


def test_invalid_keys_and_unknown_items_are_refused_safely():
    q = qc.QueueCrdt("a")
    assert q.apply({"op": "ins", "id": "i1", "key": "", "ref": 1, "l": 1, "n": "z"}) is False
    assert q.apply({"op": "ins", "id": "i2", "key": "x" * 200, "ref": 1, "l": 1, "n": "z"}) is False
    assert q.ordered() == []
    with pytest.raises(KeyError):
        q.delete("missing")
    with pytest.raises(KeyError):
        q.insert("x", after_id="missing")


def test_inserting_between_items_with_identical_keys_is_safe_and_convergent():
    a, b = qc.QueueCrdt("a"), qc.QueueCrdt("b")
    root = a.insert("root")
    b.apply(root)
    x = a.insert("x", after_id=root["id"])
    y = b.insert("y", after_id=root["id"])
    assert x["key"] == y["key"]                        # the collision this guards against
    a.apply(y), b.apply(x)
    pair = [i.id for i in a.ordered()][1:]
    z = a.insert("z", after_id=pair[0])                # "between" the equal-key pair
    w = b.insert("w", before_id=pair[1])
    a.apply(w), b.apply(z)
    assert order(a) == order(b)
    assert {i.ref for i in a.ordered()} == {"root", "x", "y", "z", "w"}
