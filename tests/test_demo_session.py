"""Demo profile cannot inherit saved receivers, media, or user settings (#523)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from demo_session import isolated_demo_profile  # noqa: E402


class DemoSessionTests(unittest.TestCase):
    def test_private_profile_is_disposable_and_contains_no_real_receiver(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            with isolated_demo_profile(parent) as session:
                self.assertEqual(session.root.parent, parent.resolve())
                self.assertEqual(session.root, session.root.resolve())
                self.assertEqual(set(session.environment()), {
                    "HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                    "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
                })
                for key, target in session.environment().items():
                    self.assertEqual(Path(target).parent, session.root, key)
                self.assertEqual(session.environment()["HOME"], str(session.home))
                self.assertEqual(session.environment()["XDG_STATE_HOME"], str(session.state_home))
                cfg = json.loads(session.config_file.read_text(encoding="utf-8"))
                self.assertEqual(cfg["device"], "")
                self.assertEqual(cfg["cast_targets"], [])
                self.assertEqual(cfg["device_uuid"], "")
                self.assertEqual(cfg["library_folders"], [])
                self.assertFalse(cfg["library_indexer"])
                self.assertFalse(cfg["keep_streaming"])
                self.assertFalse(cfg["check_release_updates"])
                self.assertFalse((session.config_home / "cast-control" /
                                  "room-checkpoint.json").exists())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(session.root.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(session.config_file.stat().st_mode), 0o600)
                profile = session.root
            self.assertFalse(profile.exists(), "Demo private data must be removed")

    def test_real_config_and_inherited_environment_are_not_touched(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            real_config = parent / "actual" / "cast-control" / "config.json"
            real_config.parent.mkdir(parents=True)
            real_config.write_text('{"device":"Living Room"}', encoding="utf-8")
            inherited = dict(os.environ)
            with isolated_demo_profile(parent) as session:
                self.assertEqual(real_config.read_text(encoding="utf-8"),
                                 '{"device":"Living Room"}')
                self.assertNotIn(str(real_config.parent.parent),
                                 session.environment().values())
                self.assertEqual(os.environ, inherited)
                # Legacy SmoothCast caches and logs use Path.home(); no
                # inherited shell home may be visible in demo mode.
                from unittest import mock
                with mock.patch.dict(os.environ, session.environment()):
                    self.assertEqual(Path.home(), session.home)
                    self.assertEqual(Path.home() / ".cache" / "cast-control",
                                     session.home / ".cache" / "cast-control")
            self.assertEqual(real_config.read_text(encoding="utf-8"),
                             '{"device":"Living Room"}')

    def test_cleanup_on_failure_and_distinct_concurrent_profiles(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            with isolated_demo_profile(parent) as first:
                with isolated_demo_profile(parent) as second:
                    self.assertNotEqual(first.root, second.root)
                    self.assertNotEqual(first.config_file, second.config_file)
            try:
                with isolated_demo_profile(parent) as session:
                    doomed = session.root
                    raise ValueError("injected setup failure")
            except ValueError:
                pass
            self.assertFalse(doomed.exists())


if __name__ == "__main__":
    unittest.main()
