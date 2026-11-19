"""GTK-independent checks for subtitle UI, cast and seek orchestration."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
METHODS = main_window_methods()
sys.path.insert(0, str(ROOT / "src"))
import streamer


class SubtitleWorkflowTests(unittest.TestCase):
    def test_external_srt_picker_persists_valid_path(self):
        picked = METHODS["_subs_file_chosen"]
        self.assertIn('self.cfg["subs"] = "pick"', picked)
        self.assertIn('self.cfg["subs_path"] = path', picked)
        self.assertIn("streamer.SUBTITLE_EXTS", picked)
        self.assertIn("save_config(self.cfg)", picked)

    def test_mkv_text_track_selector_and_auto_fallback(self):
        build = METHODS["_build_settings_card"]
        self.assertIn('"Embedded (MKV track)"', build)
        self.assertIn("self.embedded_dropdown", build)
        tracks = METHODS["_update_embedded_choices"]
        self.assertIn("track.is_text", tracks)
        self.assertIn("track.label", tracks)
        cast = METHODS["_cast_path"]
        self.assertIn('subs_mode == "auto" and subs_path is None', cast)
        self.assertIn("streamer.preferred_embedded_subtitle(media, requested)", cast)
        self.assertIn("embedded_subtitle_index=embedded.index", cast)

    def test_seek_restart_retains_embedded_subtitle(self):
        restart = METHODS["_restart_at"]
        self.assertIn("subtitle_restart.validate_restart(state, media, delay)", restart)
        self.assertIn("embedded_subtitle_index=captions.embedded_index", restart)
        self.assertLess(restart.index("subtitle_restart.validate_restart(state, media, delay)"),
                        restart.index("session.stop(device, send_stop=False)"))

    def test_burned_captions_are_not_falsely_toggleable(self):
        controls = METHODS["_refresh_controls"]
        self.assertIn("not subtitle_burned", controls)
        self.assertIn("captions", controls.lower())
        self.assertIn("self.cc_button.set_sensitive", controls)

    def test_external_burn_in_staging_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            source = path / "chosen.srt"
            source.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello", encoding="utf-8")
            with mock.patch.object(streamer, "ROOT", path):
                staged = streamer.Session()._stage_subs(source)
            self.assertEqual(staged.name, "burned_subs.srt")
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            huge = path / "huge.srt"
            with huge.open("wb") as handle:
                handle.truncate(16 * 1024 * 1024 + 1)
            with mock.patch.object(streamer, "ROOT", path):
                with self.assertRaisesRegex(streamer.StreamError, "16 MiB"):
                    streamer.Session()._stage_subs(huge)
                with self.assertRaisesRegex(streamer.StreamError, "Unsupported"):
                    streamer.Session()._stage_subs(path / "invalid.exe")


if __name__ == "__main__":
    unittest.main()
