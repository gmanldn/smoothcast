"""Regression checks for GUI actions that must not clobber active TV state.

No GTK display is needed: inspect the exact MainWindow methods for unsafe
side effects that have previously broken queue navigation and autoplay.
"""
import unittest

from gui_source import main_window_methods


class PlayerActionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.methods = main_window_methods()

    def test_busy_queue_next_does_not_preassign_current_media(self):
        for method in ("on_next", "on_prev", "_on_queue_activated"):
            with self.subTest(method=method):
                body = self.methods[method]
                self.assertNotIn("self.now_playing =", body)
                self.assertIn("self._cast_path(", body)

    def test_play_without_owned_session_uses_local_preview_not_tv(self):
        code = self.methods["toggle_play"]
        self.assertIn("if self.session is None and not self.external:", code)
        self.assertIn("self._toggle_local_preview()", code)
        self.assertNotIn("self.cast_selected()", code)
        self.assertIn("castctl.play(device)", code)  # only in the real session branch

    def test_completion_cleanup_does_not_stop_new_tv_content(self):
        code = self.methods["_on_finished"]
        self.assertIn("session.stop(device, send_stop=False)", code)
        self.assertNotIn("lambda: session.stop(device),", code)

    def test_end_of_playback_teardown_blocks_new_cast_until_finished(self):
        code = self.methods["_on_finished"]
        self.assertIn("self.busy = session is not None", code)
        self.assertIn("self._refresh_controls()", code)
        self.assertIn("def advance(_result=None):", code)
        self.assertIn("self.busy = False\n                self._cast_path(next_path, 0.0)", code)
        self.assertIn("def cleaned(_result):", code)
        self.assertIn("def failed(message):", code)
        self.assertIn("done=cleaned, failed=failed", code)

    def test_encoder_exit_does_not_release_cast_ownership(self):
        # FFmpeg can finish writing the HLS stream while the Chromecast still
        # consumes buffered segments. UI ownership must follow session state.
        controls = self.methods["_refresh_controls"]
        self.assertIn(
            "active = bool(self.session is not None and self.session.state is not None) or self.external",
            controls,
        )
        self.assertIn("local_ready = self._preview_path is not None and self.session is None", controls)
        self.assertIn(
            "if session is None or session.state is None:",
            self.methods["seek_to"],
        )
        self.assertIn(
            "self.session and self.session.state is not None",
            self.methods["_remove_queue"],
        )
        self.assertIn(
            "playback_state.hls_session_matches(",
            self.methods["_detect_external"],
        )

    def test_explicit_start_and_resume_are_distinct(self):
        gui = self.methods["_cast_path"]
        self.assertIn("offset: float | None = None", gui)
        self.assertIn("playback_state.start_offset(", gui)
        self.assertIn("self._cast_path(next_path, 0.0)", self.methods["_on_finished"])
        self.assertIn("self._cast_path(path, None)", self.methods["open_recent"])

    def test_idle_stop_sends_no_receiver_command(self):
        # Before the first poll (or any owned playback) Stop must not fall
        # through to castctl.stop/dlna.stop and disturb another app's cast.
        code = self.methods["stop_stream"]
        guard = 'self.device_state in {"IDLE", "OFFLINE", "UNKNOWN"}'
        self.assertIn(guard, code)
        self.assertIn("self._preview_path is not None", code)
        self.assertLess(code.index(guard), code.index("castctl.stop(device)"))
        self.assertLess(code.index(guard), code.index("session.stop(device, send_stop=send_stop)"))
        self.assertIn("playback_state.hls_session_matches(", code)

    def test_close_during_cast_startup_never_publishes_an_orphan(self):
        # _cast_path publishes its session in an async worker callback. If the
        # window closes first, that callback must retire local helpers (or keep
        # the saved session recoverable) instead of targeting a dead window.
        cast = self.methods["_cast_path"]
        self.assertIn("self._closing", cast)
        self.assertIn("session.stop(device, send_stop=False)", cast)
        self.assertLess(cast.index("if self._closing:"), cast.index("self.session = session"))
        self.assertIn("if self._closing:", cast[cast.index("def failed(message):"):])
        self.assertIn("self._closing = True", self.methods["_on_close"])

    def test_manual_target_does_not_switch_tv_mid_cast(self):
        # Manual IPv4 entry (Return and Add IP) must obey the same ownership
        # rule as the dropdown: remember the target, never retarget mid-cast.
        code = self.methods["_add_cast_target"]
        guard = "self.session is not None or self.busy"
        self.assertIn(guard, code)
        self.assertLess(code.index(guard), code.index('self.cfg["device"] = target'))
        self.assertIn("self.cast_ip_entry.set_text(\"\")", code)

    def test_gtk_tick_and_details_never_read_the_filesystem(self):
        # SC-069 #78: progress and segment counts are sampled in the background.
        tick = self.methods["_tick"]
        details = self.methods["_update_details"]
        for code in (tick, details):
            self.assertNotIn("ROOT.glob", code)
            self.assertNotIn("SEGMENT_GLOB", code)
        self.assertIn("self.session.progress()", tick)
        self.assertIn("self._update_details(snapshot)", tick)
        self.assertIn("segment_count()", details)
        self.assertIn('snapshot.get("out_time")', details)


    def test_loop_all_and_shuffle_are_wired(self):
        # SC-120 #129: loop-all wraps the queue; shuffle permutes it in place.
        self.assertIn('app.loop-all', self.methods["_build_menu"])
        self.assertIn('app.shuffle-queue', self.methods["_build_menu"])
        self.assertIn(
            'repeat_all=bool(self.cfg.get("loop_all"))',
            self.methods["_on_finished"],
        )
        shuffle = self.methods["_shuffle_queue"]
        self.assertIn("playback_state.shuffle_order(", shuffle)
        self.assertIn("self._rebuild_queue()", shuffle)


if __name__ == "__main__":
    unittest.main()
