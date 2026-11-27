import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bitrate_controller import Controller

LADDER = [1000, 2500, 5000, 10000]


def test_rejects_bad_ladders():
    for bad in ([], [5, 1]):
        with pytest.raises(ValueError):
            Controller(bad)


def test_steps_down_fast_on_low_buffer_and_to_a_supported_rung():
    c = Controller(LADDER, rung=3)
    d = c.observe(3000, 2.0, 0)
    assert d.change and c.rung == 1  # 2500*1.1 <= 3000


def test_steps_up_only_after_sustained_headroom_and_cooldown():
    c = Controller(LADDER, rung=0)
    for t in range(3):
        assert not c.observe(9000, 20, 100 + t).change
    assert c.observe(9000, 20, 103).change and c.rung == 1
    for t in range(10):
        assert not c.observe(9000, 20, 104 + t).change   # cool-down blocks a second climb
    assert c.rung == 1


def test_a_single_dip_resets_the_climb_and_does_not_oscillate():
    c = Controller(LADDER, rung=1)
    for t in range(3):
        c.observe(9000, 20, 100 + t)
    c.observe(9000, 8, 103)                              # buffer not healthy: counter resets
    assert not c.observe(9000, 20, 104).change and c.rung == 1


def test_never_leaves_the_ladder():
    c = Controller(LADDER, rung=0)
    assert not c.observe(1, 0, 0).change and c.rung == 0
    top = Controller(LADDER, rung=3)
    for t in range(10):
        assert not top.observe(99999, 30, 1000 + t * 100).change
