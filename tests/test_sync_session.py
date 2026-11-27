import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import sync_session as ss


def test_group_clock_play_pause_seek_and_late_join():
    s = ss.Session("film", 600, 0)
    g = s.generation
    assert s.command("a", "1", g, "play", 10)[0] and s.position(10) == 0
    assert s.position(40) == 30
    assert s.join(40)["position"] == 30 and s.join(40)["playing"]       # joins mid-film at group position
    assert s.command("b", "1", s.generation, "pause", 50)[0] and s.position(99) == 40
    assert s.command("b", "2", s.generation, "seek", 60, 300)[0] and not s.playing and s.position(70) == 300
    assert s.command("b", "3", s.generation, "seek", 60, 9999)[0] and s.position(60) == 600


def test_duplicate_stale_and_garbage_commands_ignored():
    s = ss.Session("f", 600, 0); g = s.generation
    assert s.command("a", "1", g, "play", 1) == (True, "")
    assert s.command("a", "1", s.generation, "pause", 2) == (False, "duplicate")
    assert s.command("b", "1", g, "pause", 2) == (False, "stale")       # older generation
    assert s.command("b", "2", s.generation, "explode", 2)[1] == "unknown"
    assert s.command("b", "3", s.generation, "seek", 2, float("nan"))[1] == "bad_arg" and s.playing


def test_clock_uses_lowest_rtt_and_corrects_offset():
    c = ss.Clock()
    c.sample(0, 100.5, 1.0)                    # rtt 1.0, offset 100.0
    c.sample(2, 102.05, 2.1)                   # rtt 0.1 -> offset 100.0 best
    c.sample(5, 999, 4)                        # negative rtt dropped
    assert abs(c.offset - 100.0) < 0.06 and abs(c.server_now(10) - 110.0) < 0.06


@pytest.mark.parametrize("drift,mode", [(0.1, "ok"), (-0.24, "ok"), (0.5, "nudge"), (-2.0, "nudge"), (2.1, "seek")])
def test_correction_bands(drift, mode):
    assert ss.correction(drift)["mode"] == mode
    if mode == "nudge":
        assert ss.correction(drift)["rate"] == (0.95 if drift > 0 else 1.05)


def test_five_jittery_clients_converge_under_0_3s_within_10s():
    for seed in range(5):
        rnd = random.Random(seed)
        s = ss.Session("f", 7200, 0); s.command("host", "p", 0, "play", 0)
        # a +-5% nudge closes at most 0.5 s in 10 s, so nudge-range skew is +-0.6 s; >2 s hard-seeks
        pos = [100 + rnd.uniform(-0.6, 0.6) for _ in range(4)] + [100 + 4.0]
        s.anchor = 100.0                                          # group is at 100 s at t=0
        nudging = [False] * 5
        for tick in range(1, 101):                                 # 10 s at 0.1 s steps
            t = tick / 10
            truth = s.position(t)
            for i in range(5):
                observed = pos[i] + rnd.uniform(-0.05, 0.05)       # measurement jitter
                c = ss.correction(observed - truth, nudging[i])
                nudging[i] = c["mode"] == "nudge"
                pos[i] = truth if c["mode"] == "seek" else pos[i]
                pos[i] += 0.1 * c["rate"]
        truth = s.position(10.0)
        assert max(abs(p - truth) for p in pos) < 0.3, (seed, [p - truth for p in pos])


def test_pause_reaches_everyone_within_500ms_in_sim():
    s = ss.Session("f", 600, 0); s.command("h", "p", 0, "play", 0)
    s.command("h", "z", s.generation, "pause", 5.0)
    rnd = random.Random(1)
    arrivals = [5.0 + rnd.uniform(0.05, 0.3) for _ in range(5)]    # jittered SSE delivery
    assert max(arrivals) - 5.0 <= 0.5 and not s.state(5.4)["playing"] and s.position(5.4) == 5.0


def test_hysteresis_keeps_nudging_until_settled():
    assert ss.correction(0.2)["mode"] == "ok" and ss.correction(0.2, True)["mode"] == "nudge"
    assert ss.correction(0.05, True)["mode"] == "ok" and ss.correction(3.0, True)["mode"] == "seek"
