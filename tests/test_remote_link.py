import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import remote_link as rl


def test_backoff_is_capped_jittered_and_grows():
    rng = random.Random(1)
    delays = [rl.backoff(n, rng) for n in range(12)]
    assert all(0.5 <= d <= rl.CAP_S for d in delays) and max(delays) > 15 and delays[0] <= 1.0
    assert rl.backoff(10**9, rng) <= rl.CAP_S


def test_offline_commands_are_discarded_not_replayed():
    link = rl.Link()
    assert link.submit("seek") is None
    link.snapshot_ok(1, 0)
    assert link.submit("seek") == "seek"
    link.failed()
    assert link.submit("stop") is None
    link.snapshot_ok(2, 5)
    assert link.submit("play") == "play" and link.generation == 2


def test_sleep_goes_stale_and_controls_wait_for_a_fresh_snapshot():
    link = rl.Link(); link.snapshot_ok(1, 0)
    link.tick(600)
    assert link.state == rl.STALE and not link.can_mutate()
    assert "last confirmed 600s ago" in link.label(600)
    link.snapshot_ok(1, 601)
    assert link.can_mutate()


def test_expiry_needs_fresh_login_and_failures_give_up():
    link = rl.Link(); link.snapshot_ok(1, 0)
    link.failed(401)
    link.snapshot_ok(1, 1)                       # a stray snapshot must not restore permission
    assert link.state == rl.EXPIRED and not link.can_mutate()
    link.signed_in_again(); link.snapshot_ok(2, 2)
    assert link.can_mutate()
    for _ in range(rl.GIVE_UP_AFTER):
        link.failed(503)
    assert link.state == rl.UNAVAILABLE
