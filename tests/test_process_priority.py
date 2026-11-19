"""Encoder priority (issue #247): launch arguments, opt-out, never raising."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import process_priority as pp


class EnabledTests(unittest.TestCase):
    def _cfg(self, text):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "config.json"
        if text is not None:
            path.write_text(text)
        return path

    def test_default_on_when_missing_or_unreadable(self):
        self.assertTrue(pp.enabled(self._cfg(None)))
        self.assertTrue(pp.enabled(self._cfg("{not json")))
        self.assertTrue(pp.enabled(self._cfg("[]")))

    def test_only_explicit_false_opts_out(self):
        self.assertFalse(pp.enabled(self._cfg(json.dumps({pp.SETTING: False}))))
        for value in (True, 0, "false", None):
            self.assertTrue(pp.enabled(self._cfg(json.dumps({pp.SETTING: value}))), value)


class LaunchTests(unittest.TestCase):
    def test_windows_gets_below_normal_class(self):
        self.assertEqual(pp.launch_kwargs(True, platform="win32"),
                         {"creationflags": 0x4000})
        self.assertEqual(pp.launch_kwargs(False, platform="win32"), {})

    def test_posix_has_no_spawn_kwargs(self):
        self.assertEqual(pp.launch_kwargs(True, platform="linux"), {})
        self.assertEqual(pp.launch_kwargs(True, platform="darwin"), {})

    @unittest.skipUnless(hasattr(os, "setpriority"), "POSIX only")
    def test_lower_sets_nice_on_posix_only_when_enabled(self):
        proc = mock.Mock(pid=4242)
        with mock.patch("os.setpriority") as sp:
            self.assertTrue(pp.lower(proc, True, platform="linux"))
            sp.assert_called_once_with(os.PRIO_PROCESS, 4242, pp.NICE_VALUE)
        with mock.patch("os.setpriority") as sp:
            self.assertFalse(pp.lower(proc, False, platform="linux"))
            self.assertFalse(pp.lower(proc, True, platform="win32"))
            sp.assert_not_called()

    @unittest.skipUnless(hasattr(os, "setpriority"), "POSIX only")
    def test_lower_swallows_failures(self):
        with mock.patch("os.setpriority", side_effect=PermissionError):
            self.assertFalse(pp.lower(mock.Mock(pid=1), True, platform="linux"))
        self.assertFalse(pp.lower(mock.Mock(pid=None), True, platform="linux"))


class WiringTests(unittest.TestCase):
    def test_setting_default_and_validation(self):
        import cast_widgets  # noqa: PLC0415 (no GTK import at module load)
        import config_control
        self.assertIs(cast_widgets.DEFAULTS["lower_ffmpeg_priority"], True)
        cfg = config_control.sanitise_config({"lower_ffmpeg_priority": False}, cast_widgets.DEFAULTS)
        self.assertIs(cfg["lower_ffmpeg_priority"], False)
        cfg = config_control.sanitise_config({"lower_ffmpeg_priority": "no"}, cast_widgets.DEFAULTS)
        self.assertIs(cfg["lower_ffmpeg_priority"], True)

    def test_encoder_launches_use_the_helper(self):
        for name in ("streamer.py", "dlna.py"):
            text = (ROOT / "src" / name).read_text()
            self.assertIn("process_priority.launch_kwargs", text, name)
            self.assertIn("process_priority.lower(", text, name)


if __name__ == "__main__":
    unittest.main()
