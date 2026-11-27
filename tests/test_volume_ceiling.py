import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import volume_ceiling as vc


def test_guest_request_for_100_is_clamped_and_stepped():
    g = vc.Guard(); g.set_ceiling("tv", 0.5)
    vol, why = g.decide("tv", "u", "viewer", 1.0, 0.4, 0)
    assert vol == 0.4 + vc.DEFAULT_STEP and why
    assert g.decide("tv", "u2", "viewer", 1.0, 0.5, 0)[0] == 0.5


def test_host_is_not_clamped_and_other_receivers_unaffected():
    g = vc.Guard(); g.set_ceiling("tv", 0.2)
    assert g.decide("tv", "h", "host", 1.0, 0.1, 0) == (1.0, "")
    assert g.decide("kitchen", "u", "viewer", 1.0, 0.55, 0)[0] == 0.6


def test_rate_limit_blocks_twenty_rapid_requests_and_recovers():
    g = vc.Guard(); sent = 0
    for i in range(20):
        sent += g.decide("tv", "u", "viewer", 0.3, 0.3, i * 0.01)[0] is not None
    assert sent == vc.RATE_N
    assert g.decide("tv", "u", "viewer", 0.3, 0.3, 10)[0] is not None


def test_unknown_current_is_conservative_and_bad_input_rejected():
    g = vc.Guard()
    assert g.decide("tv", "u", "viewer", 1.0, None, 0)[0] == vc.DEFAULT_CEILING / 2
    assert g.decide("tv", "u", "viewer", float("nan"), 0.1, 0)[0] is None
    assert not g.set_ceiling("", 0.5) and not g.set_ceiling("tv", 2)
