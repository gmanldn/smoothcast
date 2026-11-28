import random

import pytest

from room_events import QueueStore
from room_playback import PlaybackStore


@pytest.mark.parametrize("seed", range(20))
def test_disconnect_and_rejoin_loses_nothing_and_duplicates_nothing(seed):
    rng = random.Random(seed)
    queue, play = QueueStore(), PlaybackStore()
    issued = []
    for n in range(100):
        if rng.random() < 0.1:  # a node drops and rejoins from the replayed log
            queue, play = QueueStore.restore(queue.log), PlaybackStore.restore(play.log)
            # the rejoined node sees clients retry commands it never recorded as seen
        if issued and rng.random() < 0.3:
            target, cid, args = rng.choice(issued)
        else:
            if rng.random() < 0.5:
                target, args = "q", (rng.choice(["add", "remove", "move", "clear"]),)
                args += {"add": (["p%d" % rng.randrange(8)],), "remove": (rng.randrange(6),),
                         "move": (rng.randrange(6), rng.randrange(6)), "clear": ()}[args[0]]
            else:
                kind = rng.choice(["claim", "release", "play", "pause", "stop"])
                target, args = "p", (kind, rng.choice("ab")) + (("m", 0) if kind == "play" else ())
            cid = f"c{n}"
            issued.append((target, cid, args))
        (queue if target == "q" else play).submit(cid, *args)
        assert len(set(queue.state.items)) == len(queue.state.items)
        assert play.state.status == "idle" or play.state.owner is not None
    assert [e.seq for e in queue.log] == list(range(1, len(queue.log) + 1))
    assert [e.seq for e in play.log] == list(range(1, len(play.log) + 1))
