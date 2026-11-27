"""Driver contract for the isolated interaction benchmark (#683, part of #627).

GTK-free: the mixin's action map is exercised with a fake window, so a rename
of the volume control cannot silently drop the volume scenario again.
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import interaction_benchmark as driver  # noqa: E402


class _Driver(driver.InteractionBenchmarkMixin):
    pass


def _window(**overrides):
    base = dict(toggle_play=lambda: None, seek_to=lambda *_: None,
                _rebuild_queue=lambda: None, _remove_queue=lambda *_: None,
                _nudge_volume=lambda *_: None)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_driver_covers_every_budgeted_scenario():
    actions = _Driver()._interaction_actions(_window())
    assert set(actions) == {
        "play_pause", "seek", "volume", "queue_rebuild_1000", "queue_remove_1000",
    }


def test_driver_measures_volume_through_the_window_nudge():
    seen = []
    actions = _Driver()._interaction_actions(
        _window(_nudge_volume=lambda delta: seen.append(delta)))
    actions["volume"]()
    assert seen == [1]


def test_driver_only_runs_when_the_isolated_job_names_an_output_path():
    assert driver.samples_path({}) is None
    assert driver.samples_path({driver.SAMPLES_ENV: "   "}) is None
    assert driver.samples_path({driver.SAMPLES_ENV: "/tmp/s.json"}) == Path("/tmp/s.json")
