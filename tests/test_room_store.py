import random

from room_store import ADD, CLEAR, MOVE, REMOVE, Command, RoomStore, replay


def add(store, key, item, **kw):
    return store.submit(Command(ADD, key, item, title=item.upper(), **kw))


def test_commands_emit_ordered_events_and_replay_to_the_same_queue():
    s = RoomStore()
    add(s, "k1", "a"); add(s, "k2", "b"); add(s, "k3", "c")
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
