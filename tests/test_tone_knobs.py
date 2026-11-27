import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tone_knobs as tk


def test_neutral_emits_no_filter_and_values_clamp():
    assert tk.filter_args(None) == [] and tk.is_neutral({"bass": 0})
    assert tk.normalize({"bass": 99, "mid": "x", "treble": float("nan")}) == {"bass": 12.0, "mid": 0.0, "treble": 0.0}


def test_bass_boost_builds_shelf_and_headroom_limiter():
    args = tk.filter_args({"bass": 6})
    assert args[0] == "-af" and "bass=g=6.0:f=100" in args[1] and "alimiter" in args[1]
    cut = tk.filter_args({"treble": -4})[1]
    assert "treble=g=-4.0" in cut and "alimiter" not in cut


def test_all_three_in_order_and_no_double_filtering_with_tenband():
    chain = tk.filter_args({"treble": 3, "bass": 2, "mid": -1})[1].split(",")
    assert [c.split("=")[0] for c in chain][:3] == ["bass", "equalizer", "treble"]
    assert tk.compose({"bass": 5}, True) == ([], "Tone knobs are off while the 10-band equaliser is on.")
    assert tk.compose({"bass": 5}, False)[0]


def test_room_revision_conflicts_and_rate_limit():
    r = tk.Room()
    assert r.set("bass", 4, 0, 0)[0] and r.revision == 1
    assert not r.set("bass", 5, 0, 1)[0]                 # stale revision
    assert not r.set("bass", 5, 1, 0.1)[0]               # too fast
    assert r.set("bass", 5, 1, 1)[0] and r.gains["bass"] == 5.0
    assert not r.set("loud", 1, 2, 5)[0]
    r.reset(); assert tk.is_neutral(r.gains)
