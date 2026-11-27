"""Property tests for the room store: replay, retries, concurrent edits, rejoin (#695)."""
import pytest

pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

import room_store as rs  # noqa: E402

CFG = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
ITEMS = st.sampled_from(["a", "b", "c", "d"])
COMMANDS = st.lists(st.tuples(st.sampled_from(["add", "remove", "move", "clear"]), ITEMS,
                              st.integers(-1, 5), st.integers(0, 6)), max_size=40)


def run(commands, store=None):
    store = store or rs.RoomStore()
    for n, (kind, item, index, key) in enumerate(commands):
        store.submit(rs.Command(kind, f"k{key}-{n}", item, item.upper(), index, None))
    return store


@CFG
@given(COMMANDS)
def test_replaying_the_log_reproduces_the_queue(commands):
    store = run(commands)
    assert rs.replay(list(store.events)) == store.queue
    assert [e.seq for e in store.events] == list(range(1, len(store.events) + 1))


@CFG
@given(COMMANDS)
def test_queue_never_holds_duplicates(commands):
    ids = [i for i, _ in run(commands).queue]
    assert len(ids) == len(set(ids))


@CFG
@given(COMMANDS)
def test_retrying_every_command_changes_nothing(commands):
    store = run(commands)
    before = (store.revision, list(store.queue))
    for n, (kind, item, index, key) in enumerate(commands):
        store.submit(rs.Command(kind, f"k{key}-{n}", item, item.upper(), index, None))
    assert (store.revision, list(store.queue)) == before


@CFG
@given(COMMANDS, st.integers(0, 40))
def test_rejoin_from_any_point_converges_without_loss_or_duplicates(commands, cut):
    store = run(commands)
    replica = rs.Replica()
    assert replica.ingest(store.events_since(0)[:cut])
    assert replica.ingest(store.events_since(replica.revision))
    assert replica.ingest(store.events_since(0))          # replayed duplicates are ignored
    assert replica.queue == store.queue and replica.revision == store.revision


@CFG
@given(COMMANDS)
def test_a_gap_is_refused_not_applied(commands):
    store = run(commands)
    if len(store.events) < 2:
        return
    replica = rs.Replica()
    assert replica.ingest(store.events[1:2]) is False and replica.revision == 0

