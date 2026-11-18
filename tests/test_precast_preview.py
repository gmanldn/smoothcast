"""Source-level guards for local pre-cast film inspection (GTK-free)."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/cast_control.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "MainWindow")
METHODS = {
    node.name: ast.get_source_segment(SOURCE, node)
    for node in WINDOW.body if isinstance(node, ast.FunctionDef)
}


class PreCastPreviewTests(unittest.TestCase):
    def test_file_selection_does_not_immediately_cast(self):
        self.assertIn("self.set_selection(path)", METHODS["_file_chosen"])
        self.assertNotIn("self._cast_path(", METHODS["_file_chosen"])

    def test_scrub_without_session_stays_local(self):
        seek = METHODS["seek_to"]
        self.assertIn("if session is None and self._preview_path is not None:", seek)
        local_branch = seek.split("if session is None and self._preview_path is not None:", 1)[1]
        self.assertLess(local_branch.index("self._queue_preview(target)"),
                        local_branch.index("return"))
        self.assertLess(local_branch.index("return"), local_branch.index("self._cast_path("))

    def test_cast_uses_explicit_preview_start_offset(self):
        cast = METHODS["cast_selected"]
        self.assertIn("self._preview_position", cast)
        self.assertIn("self._cast_path(pathlib.Path(path), start_at)", cast)

    def test_duration_and_frame_are_loaded_asynchronously(self):
        selection = METHODS["set_selection"]
        self.assertIn("streamer.ffprobe(", selection)
        self.assertIn("self.seekbar.set_state(self._preview_position, duration", selection)
        self.assertIn("self._queue_preview(self._preview_position)", selection)
        self.assertIn("Async.run(work, done=done, failed=failed)", selection)

    def test_play_button_operates_on_embedded_video_not_chromecast(self):
        method = METHODS["toggle_play"]
        self.assertIn("self._toggle_local_preview()", method)
        local = method.split("if self.session is None and not self.external:", 1)[1]
        self.assertLess(local.index("self._toggle_local_preview()"),
                        local.index("device = self._device()"))
        builder = METHODS["_build_now_playing"]
        self.assertIn("self.local_video = Gtk.Video()", builder)
        self.assertIn("self.preview_overlay.add_overlay(self.local_video)", builder)

    def test_local_scrub_controls_embedded_stream_and_playhead(self):
        self.assertIn("stream.seek(int(target * 1_000_000))", METHODS["seek_to"])
        self.assertIn("stream.get_timestamp()", METHODS["_tick"])
        self.assertIn("stream.get_playing()", METHODS["_tick"])
        self.assertIn("self._preview_position", METHODS["_skip"])

    def test_cast_picks_up_current_local_playback_position(self):
        self.assertIn("stream.get_timestamp()", METHODS["cast_selected"])
        self.assertIn("self._unload_local_video()", METHODS["_cast_path"])
        self.assertIn("offset = max(0.0, stream.get_timestamp()", METHODS["_cast_path"])

    def test_duration_is_cached_without_reprobing_on_reselection(self):
        selection = METHODS["set_selection"]
        self.assertIn("self._media_cache.get(path)", selection)
        self.assertIn("info.st_mtime_ns", selection)
        self.assertIn("if cached is None or cached[0] != fingerprint:", selection)
        self.assertIn("if self._preview_path == path:", selection)

    def test_local_preview_can_work_with_offline_cast_device(self):
        controls = METHODS["_refresh_controls"]
        self.assertIn("local_ready = self._preview_path is not None", controls)
        self.assertIn("or local_ready", controls)
        self.assertIn("self.local_button.set_sensitive(local_ready", controls)

    def test_scrub_thumbnails_are_throttled_and_do_not_run_on_gtk_thread(self):
        self.assertIn("self._preview_busy", METHODS["_start_preview"])
        self.assertIn("Async.run(", METHODS["_start_preview"])
        self.assertIn("screenshot.preview_frame(", METHODS["_start_preview"])
        self.assertIn("GLib.timeout_add(180, self._start_preview)", METHODS["_queue_preview"])
        self.assertIn("Gdk.Texture.new_from_bytes(", METHODS["_start_preview"])


if __name__ == "__main__":
    unittest.main()
