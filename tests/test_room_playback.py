import random

import pytest

from room_playback import PlaybackStore, replay


def owned_playing():
    store = PlaybackStore()
    store.submit("1", "claim", "tv-app")
    store.submit("2", "play", "tv-app", "film.mp4", 3)
    return store


def test_only_the_owner_controls_playback():
    store = owned_playing()
    assert store.submit("x", "claim", "phone") == ()
    for cmd in ("pause", "stop", "release"):
        assert store.submit(cmd, cmd, "phone") == ()
    assert store.state.owner == "tv-app" and store.state.status == "playing"


def test_pause_stop_release_flow_and_replay():
    store = owned_playing()
    store.submit("3", "pause", "tv-app")
    assert store.state.status == "paused"
    store.submit("4", "stop", "tv-app")
    store.submit("5", "release", "tv-app")
    assert (store.state.owner, store.state.status) == (None, "idle")
    assert replay(store.log) == store.state


def test_second_poller_is_impossible_and_only_the_poller_reports():
    store = owned_playing()
    assert store.submit("p1", "attach_poller", "poll-a")
    assert store.submit("p2", "attach_poller", "poll-b") == ()
    assert store.submit("r1", "report", "poll-b", 9.0) == ()
    assert store.submit("r2", "report", "poll-a", 9.0)
    assert store.state.position == 9.0
    store.submit("p3", "detach_poller", "poll-a")
    assert store.submit("p4", "attach_poller", "poll-b")


def test_idempotent_ids_and_revision_fence():
    store = PlaybackStore()
    first = store.submit("c", "claim", "a")
    assert store.submit("c", "claim", "b") == first and store.state.owner == "a"
    assert store.submit("d", "release", "a", expected_revision=0) == ()
    assert store.submit("d", "release", "a", expected_revision=1)


def test_unknown_command_raises():
    with pytest.raises(ValueError):
        PlaybackStore().submit("1", "explode", "a")


@pytest.mark.parametrize("seed", range(25))
def test_random_interleavings_keep_invariants_and_replay(seed):
    rng = random.Random(seed)
    store = PlaybackStore()
    actors = ["a", "b", "c"]
    kinds = ["claim", "release", "play", "pause", "stop", "attach_poller", "detach_poller", "report"]
    issued = []
    for n in range(120):
        if issued and rng.random() < 0.25:
            cid, kind, actor, args = rng.choice(issued)  # duplicate delivery
        else:
            kind, actor = rng.choice(kinds), rng.choice(actors)
            args = {"play": ("m%d" % rng.randrange(3), rng.randrange(50)),
                    "report": (rng.randrange(100),)}.get(kind, ())
            cid = f"c{n}"
            issued.append((cid, kind, actor, args))
        store.submit(cid, kind, actor, *args)
        s = store.state
        assert s.status == "idle" or s.owner is not None   # never playing unowned
        assert s.status == "idle" or s.media is not None
    assert [e.seq for e in store.log] == list(range(1, len(store.log) + 1))
    assert replay(store.log) == store.state
