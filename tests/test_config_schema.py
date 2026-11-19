"""Schema versioning and safe migration of config.json (issue #273)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import config_control as cc

DEFAULTS = {"schema_version": 1, "quality": "balanced", "audio_gain": 6.0}


class ConfigSchemaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "config.json"

    def write(self, data):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data))

    def test_real_defaults_carry_the_current_schema_version(self):
        source = (ROOT / "src/cast_widgets.py").read_text("utf-8")
        self.assertIn(f'"schema_version": {cc.SCHEMA_VERSION},', source)

    def test_unversioned_file_migrates_keeps_settings_and_is_backed_up(self):
        original = {"quality": "high", "audio_gain": 3.0}
        self.write(original)
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertEqual((cfg["quality"], cfg["audio_gain"]), ("high", 3.0))
        self.assertEqual(cfg["schema_version"], cc.SCHEMA_VERSION)
        backup = self.path.with_name("config.json.schema0.bak")
        self.assertEqual(json.loads(backup.read_text()), original)
        self.assertEqual(json.loads(self.path.read_text()), original)  # not rewritten on load

    def test_backup_is_never_replaced(self):
        self.write({"quality": "high"})
        backup = self.path.with_name("config.json.schema0.bak")
        backup.write_text("older original")
        cc.load_file(self.path, DEFAULTS)
        self.assertEqual(backup.read_text(), "older original")

    def test_current_version_needs_no_backup(self):
        self.write({"schema_version": cc.SCHEMA_VERSION, "quality": "saver"})
        self.assertEqual(cc.load_file(self.path, DEFAULTS)["quality"], "saver")
        self.assertEqual(list(self.path.parent.glob("*.bak")), [])

    def test_missing_file_gives_defaults_and_saves_normally(self):
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertEqual(cfg, DEFAULTS)
        self.assertTrue(cc.save_file(self.path, cfg))
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], 1)

    def test_future_schema_is_read_best_effort_but_never_overwritten(self):
        future = {"schema_version": cc.SCHEMA_VERSION + 1, "quality": "saver", "new": 1}
        self.write(future)
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertEqual(cfg["quality"], "saver")
        self.assertFalse(cc.save_file(self.path, cfg))
        self.assertEqual(json.loads(self.path.read_text()), future)

    def test_invalid_versions_are_protected(self):
        for bad in ("2", -1, True, None, 1.5):
            with self.subTest(version=bad):
                self.write({"schema_version": bad, "quality": "high"})
                cc.load_file(self.path, DEFAULTS)
                self.assertFalse(cc.save_file(self.path, DEFAULTS))

    def test_failed_migration_keeps_original_and_loads_valid_keys(self):
        self.write({"quality": "high"})
        with mock.patch.object(cc, "MIGRATIONS", {0: lambda raw: 1 / 0}):
            cfg = cc.load_file(self.path, DEFAULTS)
        self.assertEqual(cfg["quality"], "high")
        self.assertFalse(cc.save_file(self.path, cfg))
        self.assertEqual(json.loads(self.path.read_text()), {"quality": "high"})

    def test_multi_step_migrations_run_in_order_without_mutating_input(self):
        steps = {
            0: lambda raw: {**raw, "quality": "high"},
            1: lambda raw: {**raw, "audio_gain": 9.0},
        }
        raw = {"quality": "saver"}
        with mock.patch.object(cc, "SCHEMA_VERSION", 2), mock.patch.object(cc, "MIGRATIONS", steps):
            migrated, original = cc.migrate(raw)
        self.assertEqual((original, migrated["schema_version"]), (0, 2))
        self.assertEqual((migrated["quality"], migrated["audio_gain"]), ("high", 9.0))
        self.assertEqual(raw, {"quality": "saver"})

    def test_missing_migration_step_is_an_error(self):
        with mock.patch.object(cc, "SCHEMA_VERSION", 3), mock.patch.object(cc, "MIGRATIONS", {0: lambda r: r}):
            with self.assertRaises(cc.ConfigSchemaError):
                cc.migrate({"schema_version": 1})

    def test_corrupt_json_is_backed_up_before_defaults_can_overwrite_it(self):
        self.write("{not json")
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertEqual(cfg, DEFAULTS)
        self.assertEqual(self.path.with_name("config.json.corrupt.bak").read_text(), "{not json")
        self.assertTrue(cc.save_file(self.path, cfg))

    def test_protection_is_cleared_by_a_later_good_load(self):
        self.write({"schema_version": 99})
        cc.load_file(self.path, DEFAULTS)
        self.write({"schema_version": 1, "quality": "high"})
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertTrue(cc.save_file(self.path, cfg))

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        self.assertTrue(cc.save_file(self.path, {"quality": "high"}))
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["config.json"])


if __name__ == "__main__":
    unittest.main()
