"""GTK-free checks that device dispatch does not mix DLNA and Google Cast."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
window = next(node for node in ast.parse(source).body
              if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
METHODS = {node.name: ast.get_source_segment(source, node)
           for node in window.body if isinstance(node, ast.FunctionDef)}


class DlnaGuiContracts(unittest.TestCase):
    def test_both_discovery_protocols_are_present_and_async(self):
        scan = METHODS["scan_devices"]
        self.assertIn("castctl.scan()", scan)
        self.assertIn("dlna.discover()", scan)
        self.assertIn("Async.run(work", scan)
        done = METHODS["_scan_done"]
        self.assertIn("self._dlna_by_key", done)
        self.assertIn("DLNA FOUND", done)

    def test_dlna_targets_identified_without_guessing_from_device_name(self):
        self.assertIn("self._dlna_by_key.get(", METHODS["_dlna_renderer"])
        self.assertIn("dlna.Renderer", METHODS["_dlna_renderer"])
        self.assertIn("renderer.host", METHODS["_device_host"])

    def test_transport_actions_never_use_catt_on_dlna(self):
        play = METHODS["toggle_play"]
        self.assertIn("dlna.play(renderer)", play)
        self.assertIn("dlna.pause(renderer)", play)
        self.assertIn("castctl.play(device)", play)
        self.assertIn("castctl.pause(device)", play)
        self.assertIn("dlna.stop(renderer)", METHODS["stop_stream"])
        self.assertIn("dlna.seek(renderer, target)", METHODS["seek_to"])
        self.assertIn("dlna.volume(renderer, value)", METHODS["_commit_volume"])
        self.assertIn("dlna.set_muted(renderer, muted)", METHODS["_on_mute"])

    def test_dlna_session_is_distinct_from_hls_cast(self):
        cast = METHODS["_cast_path"]
        self.assertIn("dlna.Session() if renderer is not None else streamer.Session()", cast)
        self.assertIn("session.start(", cast)
        self.assertIn("local_ip=streamer.host_ip(renderer.host)", cast)
        self.assertIn("session.start_transcode(", cast)
        self.assertIn("session.start_direct(", cast)
        self.assertIn("previous.stop(device, send_stop=previous.mode ==", cast)

    def test_dlna_receiver_subtitle_toggle_disabled(self):
        self.assertIn("not dlna_active", METHODS["_refresh_controls"])
        self.assertIn("if self._dlna_renderer() is not None:", METHODS["_on_cc_toggled"])

    def test_dlna_session_shutdown_requires_server_cleanup(self):
        close = METHODS["_on_close"]
        self.assertIn('self.session.mode == "dlna"', close)
        self.assertIn("session.stop(device)", close)

    def test_polling_uses_same_device_state_model(self):
        poll = METHODS["_poll_device"]
        self.assertIn("dlna.info(renderer)", poll)
        self.assertIn("castctl.info(device)", poll)
        self.assertIn("device != self._device()", poll)

if __name__ == "__main__":
    unittest.main()
