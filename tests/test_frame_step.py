"""SC-117 #126: source-accurate frame stepping (comma/period)."""
from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cast_lifecycle
import cast_session
import playback_state
from gui_shortcuts import installed_shortcuts


class FrameStepTests(unittest.TestCase):
    def test_frame_step_delta(self):
        self.assertAlmostEqual(playback_state.frame_step_delta(30), 1 / 30)
        self.assertEqual(playback_state.frame_step_delta(0.5), 2.0)
        # Unknown or invalid rates fall back to a one-second step, never zero.
        self.assertEqual(playback_state.frame_step_delta(0), 1.0)
        self.assertEqual(playback_state.frame_step_delta(None), 1.0)
        self.assertEqual(playback_state.frame_step_delta("bad"), 1.0)

    def test_frame_step_uses_the_media_frame_rate(self):
        class Fake:
            _frame_step = cast_lifecycle.LifecycleMixin._frame_step

            def __init__(self, fps):
                self.media = SimpleNamespace(fps=fps)
                self.skips = []

            def _skip(self, delta):
                self.skips.append(delta)

        fake = Fake(25.0)
        fake._frame_step(1)
        fake._frame_step(-1)
        self.assertAlmostEqual(fake.skips[0], 1 / 25)
        self.assertAlmostEqual(fake.skips[1], -1 / 25)

        unknown = Fake(0.0)
        unknown._frame_step(1)
        self.assertEqual(unknown.skips, [1.0])

    def test_step_keys_are_wired_to_the_frame_step(self):
        class Window:
            def __init__(self):
                self.steps = []

            _skip_back1 = cast_session.SessionMixin._skip_back1
            _skip_forward1 = cast_session.SessionMixin._skip_forward1

            def _frame_step(self, direction):
                self.steps.append(direction)

            def __getattr__(self, name):
                return lambda *a, **kw: None

        window = Window()
        keys = installed_shortcuts(window)
        keys["comma"]()
        keys["period"]()
        self.assertEqual(window.steps, [-1, 1])


if __name__ == "__main__":
    unittest.main()
