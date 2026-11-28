import random

from room_playback import Command, RoomPlayback, replay, PLAYING, PAUSED, IDLE


def _owned():
    r = RoomPlayback()
    assert r.submit(Command("claim", "k0", owner="ann", receiver="tv")).ok
    return r


def test_commands_emit_events_and_replay_to_the_same_state():
    r = _owned()
    r.submit(Command("play", "k1", owner="ann", item="a"))
    r.submit(Command("pause", "k2", owner="ann"))
    assert r.state.status == PAUSED and r.state.item == "a"
    assert replay(r.events) == r.state and [e.seq for e in r.events] == [1, 2, 3]


def test_only_the_owner_controls_the_receiver():
    r = _owned()
    assert r.submit(Command("play", "k1", owner="bob", item="a")).reason == "not_owner"
    assert r.submit(Command("claim", "k2", owner="bob", receiver="tv")).reason == "receiver_busy"
    assert r.revision == 1
    assert r.submit(Command("release", "k3", owner="ann")).ok
    assert r.submit(Command("claim", "k4", owner="bob", receiver="tv")).ok


def test_retry_is_idempotent_and_stale_fence_rejects():
    r = _owned()
    first = r.submit(Command("play", "k1", owner="ann", item="a"))
    again = r.submit(Command("play", "k1", owner="ann", item="a"))
    assert again.duplicate and again.event == first.event and r.revision == 2
    assert r.submit(Command("stop", "k2", owner="ann", base_revision=1)).reason == "stale_revision"
    assert r.state.status == PLAYING


def test_validation():
    r = RoomPlayback()
    assert r.submit(Command("play", "a", owner="ann", item="x")).reason == "no_owner"
    assert r.submit(Command("claim", "b", owner="", receiver="tv")).reason == "missing_owner"
    assert r.submit(Command("claim", "c", owner="ann")).reason == "missing_receiver"
    assert r.submit(Command("dance", "d", owner="ann")).reason == "unknown_command"
    r.submit(Command("claim", "e", owner="ann", receiver="tv"))
    assert r.submit(Command("pause", "f", owner="ann")).reason == "not_playing"
    assert r.submit(Command("play", "g", owner="ann")).reason == "missing_item"
    r.submit(Command("play", "h", owner="ann", item="a")); r.submit(Command("stop", "i", owner="ann"))
    assert r.state.status == IDLE and r.state.item == ""


def test_random_contention_never_gives_two_owners_and_replays_exactly():
    rng = random.Random(7)
    r = RoomPlayback()
    for n in range(400):
        who = rng.choice(["ann", "bob", "cy"])
        kind = rng.choice(["claim", "release", "play", "pause", "stop"])
        key = f"k{rng.randrange(150)}"           # many retried keys
        r.submit(Command(kind, key, owner=who, receiver="tv", item=f"i{n % 5}"))
        s = r.state
        assert (s.owner == "") == (s.receiver == "")
    assert replay(r.events) == r.state
    assert len({e.seq for e in r.events}) == len(r.events)


def test_a_rejected_key_stays_rejected_after_the_receiver_frees_up():
    r = _owned()
    busy = r.submit(Command("claim", "bob1", owner="bob", receiver="tv"))
    assert not busy.ok and busy.reason == "receiver_busy"
    assert r.submit(Command("release", "k1", owner="ann")).ok
    again = r.submit(Command("claim", "bob1", owner="bob", receiver="tv"))
    assert not again.ok and again.duplicate and again.reason == "receiver_busy"
    assert r.state.owner == ""
    assert r.submit(Command("claim", "bob2", owner="bob", receiver="tv")).ok   # a fresh intent uses a fresh key
