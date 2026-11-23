"""Schema versioning and safe migration of config.json (issue #273)."""
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import config_control as cc
import config_persistence

DEFAULTS = {"schema_version": 1, "quality": "balanced", "audio_gain": 6.0}


def _write_config_key(path: str, key: str, gate) -> None:
    defaults = {"schema_version": cc.SCHEMA_VERSION, "left": 0, "right": 0}
    config_path = Path(path)
    cfg = cc.load_file(config_path, defaults)
    gate.wait(timeout=20)
    for value in range(1, 201):
        cfg[key] = value
        if not cc.save_file(config_path, cfg):
            raise RuntimeError(f"config save failed for {key}={value}")


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

    def test_new_corruption_is_not_overwritten_without_a_fresh_backup(self):
        self.write(DEFAULTS)
        cfg = cc.load_file(self.path, DEFAULTS)
        self.path.write_text("{new corruption", encoding="utf-8")
        self.assertFalse(cc.save_file(self.path, cfg))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{new corruption")

    def test_protection_is_cleared_by_a_later_good_load(self):
        self.write({"schema_version": 99})
        cc.load_file(self.path, DEFAULTS)
        self.write({"schema_version": 1, "quality": "high"})
        cfg = cc.load_file(self.path, DEFAULTS)
        self.assertTrue(cc.save_file(self.path, cfg))

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        self.assertTrue(cc.save_file(self.path, {"quality": "high"}))
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(json.loads(self.path.read_text())["quality"], "high")
        self.assertTrue(self.path.with_name("config.json.lock").is_file())

    def test_external_refresh_keeps_local_edits_and_updates_untouched_keys(self):
        self.write(DEFAULTS)
        local = cc.load_file(self.path, DEFAULTS)
        local["quality"] = "high"
        external = dict(DEFAULTS)
        external["audio_gain"] = 9.0
        self.path.write_text(json.dumps(external), encoding="utf-8")

        self.assertTrue(cc.refresh_file(self.path, local, DEFAULTS))
        self.assertEqual(local["quality"], "high")
        self.assertEqual(local["audio_gain"], 9.0)

    def test_two_processes_keep_changed_keys_and_json_readers_never_see_partial_file(self):
        defaults = {"schema_version": cc.SCHEMA_VERSION, "left": 0, "right": 0}
        self.assertTrue(cc.save_file(self.path, defaults))
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(3)
        workers = [
            context.Process(target=_write_config_key, args=(str(self.path), key, gate))
            for key in ("left", "right")
        ]
        for worker in workers:
            worker.start()
        gate.wait(timeout=20)
        while any(worker.is_alive() for worker in workers):
            self.assertIsInstance(json.loads(self.path.read_text(encoding="utf-8")), dict)
        for worker in workers:
            worker.join(timeout=5)
            self.assertEqual(worker.exitcode, 0)
        final = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((final["left"], final["right"]), (200, 200))

    def test_debounced_writer_coalesces_updates_off_the_calling_thread(self):
        writes = []
        caller = threading.get_ident()
        writer = cc.DebouncedWriter(
            lambda cfg: writes.append((cfg, threading.get_ident())) or True,
            delay=60.0,
        )
        writer.submit({"value": 1})
        writer.submit({"value": 2})
        writer.submit({"value": 3})
        self.assertTrue(writer.flush())
        self.assertEqual([item[0] for item in writes], [{"value": 3}])
        self.assertNotEqual(writes[0][1], caller)

    def test_debounced_writer_reports_failed_persistence_on_flush(self):
        writer = cc.DebouncedWriter(lambda _cfg: False, delay=60.0)
        writer.submit({"value": 1})
        self.assertFalse(writer.flush())

    def test_gui_persistence_bridge_flushes_the_latest_config_snapshot(self):
        self.write(DEFAULTS)
        config_persistence.configure(self.path, DEFAULTS, lambda _message: None)
        cfg = cc.load_file(self.path, DEFAULTS)
        cfg["quality"] = "high"
        config_persistence.save_config(cfg)
        self.assertTrue(config_persistence.flush_config())
        self.assertEqual(json.loads(self.path.read_text())["quality"], "high")


if __name__ == "__main__":
    unittest.main()
