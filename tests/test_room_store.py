import random

import pytest

from room_store import ADD, CLEAR, MOVE, REMOVE, Command, Replica, RoomStore, replay


def add(store, key, item, **kw):
    return store.submit(Command(ADD, key, item, title=item.upper(), **kw))


def test_commands_emit_ordered_events_and_replay_to_the_same_queue():
    s = RoomStore()
    for n, item in enumerate("abc", 1):
        add(s, f"k{n}", item)
    s.submit(Command(MOVE, "k4", "c", index=0))
    s.submit(Command(REMOVE, "k5", "b"))
    assert [e.seq for e in s.events] == [1, 2, 3, 4, 5]
    assert [i for i, _ in s.queue] == ["c", "a"]
    assert replay(s.events) == s.queue


def test_retry_with_same_key_is_idempotent():
    s = RoomStore()
    first = add(s, "k1", "a")
    again = add(s, "k1", "a")
    assert again.duplicate and again.event == first.event
    assert s.revision == 1


def test_stale_revision_fence_rejects_without_effect():
    s = RoomStore()
    add(s, "k1", "a")
    res = s.submit(Command(ADD, "k2", "b", base_revision=0))
    assert not res.ok and res.reason == "stale_revision" and s.revision == 1
    assert s.submit(Command(ADD, "k3", "b", base_revision=1)).ok


def test_rejects_duplicates_and_unknown_items():
    s = RoomStore()
    add(s, "k1", "a")
    assert add(s, "k2", "a").reason == "duplicate_item"
    assert s.submit(Command(REMOVE, "k3", "zzz")).reason == "unknown_item"
    assert s.submit(Command("explode", "k4")).reason == "unknown_command"


def test_random_retried_edits_never_duplicate_or_lose_items():
    rng = random.Random(7)
    s = RoomStore()
    live = set()
    for n in range(300):
        item = f"i{rng.randrange(12)}"
        key = f"k{n}"
        cmd = (Command(REMOVE, key, item) if item in live and rng.random() < 0.5
               else Command(ADD, key, item, title=item))
        for _ in range(rng.choice((1, 1, 2, 3))):      # retries and reordered duplicates
            s.submit(cmd)
        if cmd.kind == ADD and item not in live:
            live.add(item)
        elif cmd.kind == REMOVE:
            live.discard(item)
    ids = [i for i, _ in s.queue]
    assert len(ids) == len(set(ids)) and set(ids) == live
    assert replay(s.events) == s.queue
    s.submit(Command(CLEAR, "kc"))
    assert s.queue == []


def test_replica_rejoin_catches_up_and_ignores_duplicates_and_refuses_gaps():
    s = RoomStore()
    for n, item in enumerate("abc", 1):
        add(s, f"k{n}", item)
    r = Replica()
    assert r.ingest(s.events[:1])
    assert not r.ingest(s.events[2:])            # gap: seq 3 without 2
    assert r.revision == 1
    assert r.ingest(s.events_since(r.revision)) and r.ingest(s.events)   # replay of old events is harmless
    assert r.queue == s.queue and r.revision == 3


hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

_cmd = st.tuples(st.sampled_from([ADD, REMOVE, MOVE, CLEAR]), st.sampled_from("abcde"), st.integers(-1, 6),
                 st.one_of(st.none(), st.integers(0, 12)))


@settings(max_examples=150, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.too_slow])
@given(ops=st.lists(_cmd, max_size=40), dupes=st.lists(st.integers(0, 39), max_size=20), cut=st.integers(0, 40))
def test_any_command_sequence_with_retries_and_rejoin_converges_without_duplicates(ops, dupes, cut):
    s = RoomStore()
    cmds = [Command(k, f"key{n}", item, title=item, index=i, base_revision=None) for n, (k, item, i, _b) in enumerate(ops)]
    live = Replica()
    stale = Replica()
    for n, cmd in enumerate(cmds):
        s.submit(cmd)
        live.ingest(s.events_since(live.revision))
        if n == cut:
            stale.ingest(s.events)               # a client that disconnects here
    for n in dupes:                               # late retries of earlier commands change nothing
        if n < len(cmds):
            before = (s.revision, s.queue)
            s.submit(cmds[n])
            assert (s.revision, s.queue) == before
    stale.ingest(s.events_since(stale.revision))  # rejoin
    ids = [i for i, _ in s.queue]
    assert len(ids) == len(set(ids))
    assert live.queue == stale.queue == s.queue == replay(s.events)


def test_a_rejected_key_stays_rejected_even_after_the_state_changes():
    s = RoomStore()
    add(s, "k1", "a")
    assert add(s, "dup", "a").reason == "duplicate_item"
    s.submit(Command(REMOVE, "k2", "a"))
    again = add(s, "dup", "a")                    # the old rejected intent must not now succeed
    assert not again.ok and again.duplicate and again.reason == "duplicate_item"
    assert s.queue == []
    assert add(s, "fresh", "a").ok                # a new intent uses a new key
