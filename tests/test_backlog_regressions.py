"""Guard recovered feature ideas and high-value receiver/preview regressions.

These tests deliberately avoid importing GTK or opening a desktop window.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
APP = next(node for node in ast.parse(GUI).body
           if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
METHODS = {
    node.name: ast.get_source_segment(GUI, node)
    for node in APP.body if isinstance(node, ast.FunctionDef)
}
sys.path.insert(0, str(ROOT / "src"))
import castctl
from playback_state import playback_ended


class BacklogPreservationTests(unittest.TestCase):
    def test_original_50_preserved_and_linked_from_current_backlog(self):
        archived = (ROOT / "docs" / "IMPROVEMENTS_ORIGINAL_50_20261118.md").read_text()
        current = (ROOT / "IMPROVEMENTS.md").read_text()
        original_nums = [int(i) for i in re.findall(r"(?m)^(\d+)\. ", archived)]
        recovered_nums = [int(i) for i in re.findall(r"(?m)^(\d+)\. ", current)]
        self.assertEqual(original_nums[:50], list(range(1, 51)))
        self.assertEqual(recovered_nums[:132], list(range(1, 133)))
        self.assertIn("docs/IMPROVEMENTS_ORIGINAL_50_20261118.md", current)
        self.assertIn("7b8bd62c8a06", current)
        self.assertIn("A–B segment repeat", current)
        self.assertIn("10-band equaliser", current)
        self.assertIn("Queue drag-and-drop reorder", current)
        self.assertIn("Automatic theme by time", current)

    def test_old_completion_markers_remain_historical_not_marked_verified(self):
        archived = (ROOT / "docs" / "IMPROVEMENTS_ORIGINAL_50_20261118.md").read_text()
        self.assertIn("## Done", archived)
        current = (ROOT / "IMPROVEMENTS.md").read_text()
        self.assertIn("historical claims", current)
        self.assertIn("not evidence of current working behaviour", current)


class ReceiverSafetyTests(unittest.TestCase):
    def test_partial_receiver_status_does_not_finish_active_video(self):
        for partial in ({"volume_level": 0.5}, {"title": "Film"},
                        {"player_state": "PLAYING-ish"}, {"player_state": None}):
            state = castctl.player_state(partial)
            self.assertEqual(state, "UNKNOWN")
            self.assertFalse(playback_ended(
                "PLAYING", state, has_session=True, busy=False
            ))
        self.assertTrue(playback_ended(
            "PLAYING", castctl.player_state({"player_state": "IDLE"}),
            has_session=True, busy=False,
        ))

    def test_receiver_swap_discards_pending_debounced_volume(self):
        changes = METHODS["_on_device_selected"]
        self.assertIn("GLib.source_remove(self._volume_job)", changes)
        self.assertIn("self._volume_target = None", changes)
        self.assertLess(changes.index("self._volume_target = None"),
                        changes.index('self.cfg["device"] = name'))
        queued = METHODS["_on_volume_changed"]
        self.assertIn("self._volume_target = self._device()", queued)
        commit = METHODS["_commit_volume"]
        self.assertIn("target != self._device()", commit)
        self.assertIn("device = target", commit)
        self.assertNotIn("device = self._device()", commit)

    def test_active_receiver_media_not_replaced_by_queue_selection(self):
        selection = METHODS["set_selection"]
        self.assertIn("self.session is not None or self.external or self.busy", selection)
        guard = selection.index("self.session is not None or self.external or self.busy")
        media_change = selection.index("self.media = None")
        self.assertLess(guard, media_change)
        self.assertIn("self._refresh_controls()", selection[:media_change])

    def test_delete_preview_clears_local_only_not_cast(self):
        retire = METHODS["_retire_unqueued_preview"]
        self.assertIn("self.session is not None or self.external", retire)
        self.assertIn("self._preview_generation += 1", retire)
        self.assertIn("self._preview_pending = None", retire)
        self.assertIn("self._unload_local_video()", retire)
        self.assertIn("self._preview_path = None", retire)
        self.assertIn("self.seekbar.set_state(0.0, 0.0, 0.0)", retire)
        self.assertIn("self._retire_unqueued_preview()", METHODS["_remove_queue"])
        self.assertIn("self._retire_unqueued_preview()", METHODS["clear_queue"])


if __name__ == "__main__":
    unittest.main()
