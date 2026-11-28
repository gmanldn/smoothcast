import random

import pytest

from room_events import QueueStore, replay


def test_replay_reproduces_state():
    store = QueueStore()
    store.submit("1", "add", ["a", "b", "c"])
    store.submit("2", "move", 0, 2)
    store.submit("3", "remove", 1)
    rebuilt = replay(store.log)
    assert rebuilt.items == store.state.items == ["b", "a"]
    assert rebuilt.revision == store.state.revision == 3


def test_command_id_is_idempotent():
    store = QueueStore()
    first = store.submit("x", "add", ["a"])
    again = store.submit("x", "add", ["a", "b"])
    assert first == again and store.state.items == ["a"] and store.state.revision == 1


def test_revision_fence_rejects_stale_edit_and_allows_retry():
    store = QueueStore()
    store.submit("1", "add", ["a"])
    assert store.submit("2", "add", ["b"], expected_revision=0) == ()
    assert store.state.items == ["a"]
    assert store.submit("2", "add", ["b"], expected_revision=1)
    assert store.state.items == ["a", "b"]


def test_noops_emit_no_events():
    store = QueueStore()
    assert store.submit("1", "remove", 0) == ()
    assert store.submit("2", "clear") == ()
    store.submit("3", "add", ["a", "a"])
    assert store.submit("4", "add", ["a"]) == ()
    assert store.state.revision == 1 and store.state.items == ["a"]


def test_unknown_command_raises():
    with pytest.raises(ValueError):
        QueueStore().submit("1", "explode")


@pytest.mark.parametrize("seed", range(25))
def test_random_commands_with_retries_replay_to_same_state_without_duplicates(seed):
    rng = random.Random(seed)
    store = QueueStore()
    issued = []
    for n in range(80):
        if issued and rng.random() < 0.3:  # retry / duplicate delivery
            cid, kind, args = rng.choice(issued)
        else:
            cid, kind = f"c{n}", rng.choice(["add", "add", "remove", "move", "clear"])
            args = {"add": ([f"p{rng.randrange(12)}" for _ in range(3)],),
                    "remove": (rng.randrange(-1, 8),),
                    "move": (rng.randrange(8), rng.randrange(8)),
                    "clear": ()}[kind]
            issued.append((cid, kind, args))
        store.submit(cid, kind, *args)
    assert [e.seq for e in store.log] == list(range(1, len(store.log) + 1))
    assert len(set(store.state.items)) == len(store.state.items)
    rebuilt = replay(store.log)
    assert rebuilt.items == store.state.items and rebuilt.revision == store.state.revision
