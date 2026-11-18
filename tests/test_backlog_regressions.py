"""Guard recovered feature ideas and high-value receiver/preview regressions.

These tests deliberately avoid importing GTK or opening a desktop window.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
METHODS = main_window_methods()
sys.path.insert(0, str(ROOT / "src"))
import castctl
from playback_state import playback_ended


class BacklogPreservationTests(unittest.TestCase):
    def test_issues_are_canonical_and_old_root_backlog_is_absent(self):
        self.assertFalse((ROOT / "IMPROVEMENTS.md").exists())
        workflow = (ROOT / "docs" / "ISSUES.md").read_text(encoding="utf-8")
        migration = (
            ROOT / "docs" / "ISSUES_MIGRATION_20261118.md"
        ).read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/gmanldn/smoothcast/issues", workflow)
        self.assertIn("SC-001", workflow)
        self.assertIn("SC-132", workflow)
        self.assertIn("ISSUES_MIGRATION_20261118.md", workflow)
        self.assertIn("132 numbered proposals", migration)
        self.assertIn("b76579c12f6a202188cc7964a0de06c09bd5aa9e", migration)
        self.assertIn("docs/ISSUES.md", agents)
        self.assertIn("docs/ISSUES.md", readme)
        self.assertIn("GitHub Issues", agents)

    def test_original_fifty_are_still_archived_verbatim(self):
        archived = (ROOT / "docs" / "IMPROVEMENTS_ORIGINAL_50_20261118.md").read_text(
            encoding="utf-8"
        )
        original_nums = [int(i) for i in re.findall(r"(?m)^(\d+)\. ", archived)]
        self.assertEqual(original_nums[:50], list(range(1, 51)))
        self.assertIn("## Done", archived)
        workflow = (ROOT / "docs" / "ISSUES.md").read_text(encoding="utf-8")
        migration = (
            ROOT / "docs" / "ISSUES_MIGRATION_20261118.md"
        ).read_text(encoding="utf-8")
        self.assertIn("IMPROVEMENTS_ORIGINAL_50_20261118.md", workflow)
        self.assertIn("IMPROVEMENTS_ORIGINAL_50_20261118.md", migration)
        self.assertIn("historical", migration.lower())
        self.assertIn("duplicate", migration.lower())


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

    def test_offline_and_cancelled_reports_never_finish_the_owned_film(self):
        # Losing status (offline/unknown), having no owned session, being busy,
        # or an already-idle predecessor must all fail to advance the queue.
        for state in ("OFFLINE", "UNKNOWN"):
            self.assertFalse(playback_ended(
                "PLAYING", state, has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=False, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=True, busy=True))
        self.assertFalse(playback_ended("IDLE", "IDLE", has_session=True, busy=False))
        # A paused film that reaches IDLE is still a natural completion.
        self.assertTrue(playback_ended("PAUSED", "IDLE", has_session=True, busy=False))

    def test_completion_advances_exactly_once(self):
        finished = METHODS["_maybe_finished"]
        self.assertIn(
            "if self._finished_handled or self.busy or self.session is None:", finished)
        self.assertLess(finished.index("self._finished_handled = True"),
                        finished.index("self._on_finished()"))

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

    def test_rejected_volume_change_is_not_displayed_as_confirmed(self):
        commit = METHODS["_commit_volume"]
        reject = METHODS["_reject_volume"]
        # Stale targets, offline receivers, command failures and silent
        # castctl rejections all route through the revert helper.
        self.assertIn("self._reject_volume(", commit)
        self.assertIn("if not ok:", commit)
        self.assertIn("failed=lambda msg: self._reject_volume(", commit)
        self.assertLess(commit.index("if not ok:"),
                        commit.index("self._reject_volume(message"))
        # The unconfirmed value is replaced by the last known receiver value
        # without re-scheduling another debounce.
        self.assertIn("castctl.volume_percent(self.device_info)", reject)
        self.assertIn("self.volume_scale.set_value(known)", reject)
        self.assertIn("self._volume_user_ts = 0.0", reject)
        self.assertIn("self._poll_device()", reject)
        self.assertLess(reject.index("self._syncing = True"),
                        reject.index("self.volume_scale.set_value(known)"))
        self.assertGreater(reject.index("finally:"),
                           reject.index("self.volume_scale.set_value(known)"))

    def test_cc_toggle_persists_acknowledged_state_and_reverts_failures(self):
        toggle = METHODS["_on_cc_toggled"]
        restore = METHODS["_restore_cc_toggle"]
        # An acknowledged Off must be recorded, or the next status refresh
        # would derive the toggle from subtitle presence and switch it back on.
        self.assertIn('self.cfg["subs"] = (', toggle)
        self.assertIn('else "off"', toggle)
        self.assertIn("save_config(self.cfg)", toggle)
        # A failed or refused command restores the prior toggle without
        # emitting another receiver command.
        self.assertGreaterEqual(toggle.count("self._restore_cc_toggle(not on)"), 2)
        self.assertIn("self.cc_button.set_active(active)", restore)
        self.assertIn("self._syncing = True", restore)
        refresh = METHODS["_refresh_controls"]
        self.assertIn('self.cfg["subs"] != "off"', refresh)
        self.assertIn("subtitle_burned", refresh)

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
