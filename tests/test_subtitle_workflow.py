"""GTK-independent checks for subtitle UI, cast and seek orchestration."""
from __future__ import annotations

import pathlib
import re
from pathlib import Path
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest import mock

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
METHODS = main_window_methods()
sys.path.insert(0, str(ROOT / "src"))
import streamer
import subtitle_delay
import subtitle_encoding
import subtitle_style


class SubtitleWorkflowTests(unittest.TestCase):
    def test_picker_and_drop_share_subtitle_selection(self):
        self.assertIn("self._select_subtitle_file(gfile)", METHODS["_subs_file_chosen"])
        names = ("_drop_subtitle", "_select_subtitle_file", "_sync_subtitle_selection")
        source = "class Window:\n" + "\n".join(
            textwrap.indent(textwrap.dedent(METHODS[name]), "    ") for name in names
        )
        save_config = mock.Mock()
        namespace = {
            "pathlib": pathlib, "re": re, "streamer": streamer,
            "save_config": save_config, "subtitle_delay": subtitle_delay,
            "subtitle_encoding": subtitle_encoding, "subtitle_style": subtitle_style,
        }
        exec(compile(source, "<subtitle drop handlers>", "exec"), namespace)
        window = namespace["Window"]()
        window.cfg = {"subs": "auto", "subs_path": ""}
        window.toast = mock.Mock()
        window._dlna_renderer = mock.Mock(return_value=None)
        window._preview_path = None
        window.subs_dropdown = mock.Mock()
        window.subs_detail = mock.Mock()
        window._subs_status_text = mock.Mock(return_value="Using film.en.ass")

        def drop(paths):
            files = [SimpleNamespace(get_path=lambda path=path: path) for path in paths]
            return window._drop_subtitle(None, SimpleNamespace(get_files=lambda: files), 0, 0)

        with tempfile.TemporaryDirectory() as folder:
            subtitle = Path(folder) / "film.en.ass"
            subtitle.write_text(
                r"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\i1}Hello",
                encoding="utf-8",
            )
            self.assertTrue(drop([str(subtitle)]))
            self.assertFalse(drop([str(subtitle), str(subtitle)]))
            self.assertFalse(drop([None]))
            self.assertFalse(drop([str(subtitle.with_suffix(".mp4"))]))
            self.assertFalse(drop([str(subtitle.with_suffix(".srt"))]))
        self.assertEqual(window.cfg, {"subs": "pick", "subs_path": str(subtitle)})
        window.subs_dropdown.set_selected.assert_called_once_with(2)
        window.subs_detail.set_text.assert_called_with(
            "film.en.ass · Language: en · Burn-in required\nHello"
        )
        save_config.assert_called_once_with(window.cfg)
        self.assertFalse(window._syncing)

    def test_mkv_text_track_selector_and_auto_fallback(self):
        build = METHODS["_build_settings_card"]
        self.assertIn('"Embedded (MKV track)"', build)
        self.assertIn("self.embedded_dropdown", build)
        tracks = METHODS["_update_embedded_choices"]
        self.assertIn("track.is_supported", tracks)
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
