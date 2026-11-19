"""SC-117 #126: source-accurate frame stepping (comma/period)."""
from __future__ import annotations

import pathlib
import sys
import textwrap
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui_source import main_window_methods
import playback_state


class FrameStepTests(unittest.TestCase):
    def test_frame_step_delta(self):
        self.assertAlmostEqual(playback_state.frame_step_delta(30), 1 / 30)
        self.assertEqual(playback_state.frame_step_delta(0.5), 2.0)
        # Unknown or invalid rates fall back to a one-second step, never zero.
        self.assertEqual(playback_state.frame_step_delta(0), 1.0)
        self.assertEqual(playback_state.frame_step_delta(None), 1.0)
        self.assertEqual(playback_state.frame_step_delta("bad"), 1.0)

    def test_frame_step_uses_the_media_frame_rate(self):
        namespace = {"playback_state": playback_state}
        code = "class M:\n" + textwrap.indent(
            textwrap.dedent(main_window_methods()["_frame_step"]), "    ")
        exec(compile(code, "<frame-step>", "exec"), namespace)

        class Fake(namespace["M"]):
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
        methods = main_window_methods()
        self.assertIn("self._frame_step(-1)", methods["_skip_back1"])
        self.assertIn("self._frame_step(1)", methods["_skip_forward1"])


if __name__ == "__main__":
    unittest.main()
