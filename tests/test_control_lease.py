import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import control_lease as cl

S = (1, "film", "tv")


def test_competing_seeks_have_one_owner_with_retry_after():
    l = cl.Lease()
    assert l.request("a", "seek", S, 0, name="Ann") == (True, 0.0)
    ok, wait = l.request("b", "seek", S, 1)
    assert not ok and 0 < wait <= cl.TTL_S
    assert l.request("a", "skip", S, 2)[0]          # owner renews
    assert l.status(S, 3) == {"held": True, "by": "Ann", "seconds_left": cl.TTL_S - 1.0}


def test_play_pause_volume_ungated_and_host_takes_over():
    l = cl.Lease(); l.request("a", "seek", S, 0)
    assert l.request("b", "pause", S, 1)[0] and l.request("b", "volume", S, 1)[0]
    assert l.request("h", "seek", S, 1, role="host")[0] and l.owner == "h"


def test_lease_dies_with_new_film_receiver_generation_or_idle():
    l = cl.Lease(); l.request("a", "seek", S, 0)
    for other in ((2, "film", "tv"), (1, "film2", "tv"), (1, "film", "kitchen")):
        assert l.request("b", "seek", other, 1)[0]
        l.release(host=True); l.request("a", "seek", S, 0)
    l.release(host=True); l.request("a", "seek", S, 0)
    assert l.request("b", "seek", S, cl.TTL_S + 0.1)[0]


def test_revoke_and_release_rules():
    l = cl.Lease(); l.request("a", "seek", S, 0)
    l.release("b"); assert l.owner == "a"
    l.revoke("a"); assert l.owner is None and l.status(S, 0) == {"held": False}
