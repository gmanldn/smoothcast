"""Validate real configuration loading without importing or starting GTK."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

import config_control


ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCE = (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")


def real_defaults():
    tree = ast.parse(GUI_SOURCE)
    declaration = next(node for node in tree.body if
                       isinstance(node, ast.AnnAssign)
                       and isinstance(node.target, ast.Name)
                       and node.target.id == "DEFAULTS")
    value = ast.get_source_segment(GUI_SOURCE, declaration.value)
    return ast.literal_eval(value.replace("castctl.DEFAULT_DEVICE", "'TV'"))


def load_from_source(path, defaults):
    """Execute the actual load_config function, without any gi imports."""
    tree = ast.parse(GUI_SOURCE)
    method = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "load_config")
    source = ast.get_source_segment(GUI_SOURCE, method)
    namespace = {"json": json, "config_control": config_control,
                 "CONFIG_FILE": path, "DEFAULTS": defaults}
    exec(compile(source, "<actual-config-loader>", "exec"), namespace)
    return namespace["load_config"]()


class ConfigRecoveryTests(unittest.TestCase):
    def test_invalid_fields_fall_back_without_losing_valid_neighbours(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({
                "recents": None,
                "audio_gain": "loud",
                "audio": "unknown",
                "quality": "high",
                "device": "Living TV",
                "color_scheme": "force-light",
                "positions": {"film.mkv": 32.5, "bad.mkv": "later"},
                "cast_targets": ["192.168.1.10", None, 42],
                "window_width": "huge",
                "playback_speed": float("nan"),
                "unexpected": "not persisted",
            }), encoding="utf-8")
            defaults = real_defaults()
            config = load_from_source(path, defaults)
            self.assertEqual(config["recents"], [])
            self.assertEqual(config["audio_gain"], defaults["audio_gain"])
            self.assertEqual(config["audio"], defaults["audio"])
            self.assertEqual(config["quality"], "high")
            self.assertEqual(config["device"], "Living TV")
            self.assertEqual(config["color_scheme"], "force-light")
            self.assertEqual(config["positions"], {"film.mkv": 32.5})
            self.assertEqual(config["cast_targets"], ["192.168.1.10"])
            self.assertEqual(config["window_width"], defaults["window_width"])
            self.assertEqual(config["playback_speed"], 1.0)
            self.assertNotIn("unexpected", config)

    def test_independent_mutable_defaults_across_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            defaults = real_defaults()
            first = load_from_source(path, defaults)
            first["recents"].append("film.mkv")
            first["positions"]["film.mkv"] = 44.5
            first["subtitle_track_by_file"]["film.mkv"] = 1
            second = load_from_source(path, defaults)
            self.assertEqual(second["recents"], [])
            self.assertEqual(second["positions"], {})
            self.assertEqual(second["subtitle_track_by_file"], {})
            self.assertEqual(defaults["recents"], [])
            self.assertEqual(defaults["positions"], {})

    def test_corrupt_json_recovers_defaults_without_gui(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.json"
            path.write_text('{"audio":null,"recents":', encoding="utf-8")
            self.assertEqual(load_from_source(path, real_defaults()),
                             real_defaults())

    def test_invalid_track_selections_and_boolean_numbers_rejected(self):
        defaults = real_defaults()
        result = config_control.sanitise_config({
            "audio_track_by_file": {"a.mkv": 1, "b.mkv": "foo", "c.mkv": 99999},
            "subtitle_track_by_file": {"a.mkv": 2, "b.mkv": True},
            "direct": 1,
            "burn_subs": False,
            "rotation": 45,
            "sleep_timer_minutes": -1,
            "audio_gain": float("inf"),
        }, defaults)
        self.assertEqual(result["audio_track_by_file"], {"a.mkv": 1})
        self.assertEqual(result["subtitle_track_by_file"], {"a.mkv": 2})
        self.assertEqual(result["direct"], defaults["direct"])
        self.assertFalse(result["burn_subs"])
        self.assertEqual(result["rotation"], 0)
        self.assertEqual(result["sleep_timer_minutes"], 0)
        self.assertEqual(result["audio_gain"], defaults["audio_gain"])

    def test_new_config_validator_is_installed_as_a_python_module(self):
        package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"config_control"', package)
        self.assertIn("import config_control", GUI_SOURCE)
        self.assertIn("config_control.sanitise_config(raw, DEFAULTS)", GUI_SOURCE)


    def test_favourites_are_bounded_strings(self):
        defaults = real_defaults()
        raw = {"favourites": ["/a.mp4", 5, "", "/b.mp4"] + [f"/f{i}.mp4" for i in range(20)]}
        cfg = config_control.sanitise_config(raw, defaults)
        self.assertTrue(all(isinstance(p, str) and p for p in cfg["favourites"]))
        self.assertLessEqual(len(cfg["favourites"]), 16)
        self.assertNotIn(5, cfg["favourites"])


    def test_device_favourites_and_last_used_are_bounded(self):
        defaults = real_defaults()
        raw = {
            "device_favourites": ["TV"] + [f"D{i}" for i in range(20)],
            "device_last_used": {"TV": 5.0, "bad": "x"},
        }
        cfg = config_control.sanitise_config(raw, defaults)
        self.assertLessEqual(len(cfg["device_favourites"]), 16)
        self.assertEqual(cfg["device_last_used"], {"TV": 5.0})


if __name__ == "__main__":
    unittest.main()
