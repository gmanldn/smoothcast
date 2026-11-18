"""HLS short-clip readiness and safe post-encoder session recovery.

Pure/temporary-file tests; never launch GTK, FFmpeg or touch the user's TV.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import playback_state
import streamer


class HlsPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.root = Path(self.home.name)
        self.root_patch = mock.patch.object(streamer, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def publish(self, segments, *, finalized=False):
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:4"]
        for index, content in enumerate(segments):
            name = f"segment-{index:05d}.ts"
            (self.root / name).write_bytes(content)
            lines.extend(["#EXTINF:2.000,", name])
        if finalized:
            lines.append("#EXT-X-ENDLIST")
        (self.root / streamer.HLS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_single_final_segment_is_ready_on_clean_encoder_exit(self):
        self.publish([b"real MPEG-TS bytes"], finalized=True)
        session = streamer.Session()
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = 0
        self.assertTrue(streamer._hls_playlist_ready(finalized=True))
        self.assertTrue(session._wait_for_segments(0.1))

    def test_in_progress_hls_needs_two_published_segments(self):
        self.publish([b"one"], finalized=False)
        self.assertFalse(streamer._hls_playlist_ready())
        self.assertFalse(streamer._hls_playlist_ready(finalized=True))
        self.publish([b"first", b"second"], finalized=False)
        self.assertTrue(streamer._hls_playlist_ready())

    def test_failed_encoder_must_not_cast_even_if_segment_exists(self):
        self.publish([b"segment"], finalized=True)
        session = streamer.Session()
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = 1
        self.assertFalse(session._wait_for_segments(0.1))

    def test_missing_empty_or_unlisted_segments_rejected(self):
        self.publish([b"segment"], finalized=True)
        (self.root / "segment-00000.ts").unlink()
        self.assertFalse(streamer._hls_playlist_ready(finalized=True))
        (self.root / "segment-00000.ts").write_bytes(b"")
        self.assertFalse(streamer._hls_playlist_ready(finalized=True))
        (self.root / "segment-00000.ts").write_bytes(b"valid")
        (self.root / streamer.HLS_NAME).write_text(
            "#EXTM3U\n#EXTINF:1,\n../secret.ts\n#EXT-X-ENDLIST\n"
        )
        self.assertFalse(streamer._hls_playlist_ready(finalized=True))

    def test_playlist_endlist_is_required_when_encoder_has_exited(self):
        self.publish([b"segment"], finalized=False)
        session = streamer.Session()
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = 0
        self.assertFalse(session._wait_for_segments(0.1))

    def test_completed_encoder_and_live_server_can_be_recovered(self):
        self.publish([b"final"], finalized=True)
        session = streamer.Session()
        session.state = streamer.SessionState(
            file="/test/film.mkv", mode="transcode",
            offset=0, duration=2.0, device="TV", title="Film",
            stream_url="http://192.168.1.10:8767/movie.m3u8",
        )
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = 0
        with mock.patch.object(streamer, "_server_healthy", return_value=True):
            self.assertFalse(session.active())
            self.assertTrue(session.recoverable_hls())
        with mock.patch.object(streamer, "_server_healthy", return_value=False):
            self.assertFalse(session.recoverable_hls())

    def test_running_encoder_retains_original_semantics(self):
        session = streamer.Session()
        session.state = streamer.SessionState(
            file="/test/film.mkv", mode="transcode",
            offset=0, duration=10.0, device="TV", title="Film",
        )
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = None
        self.assertTrue(session.active())


class ReceiverOwnershipTests(unittest.TestCase):
    URL = "http://192.168.1.10:8767/movie.m3u8"

    def test_only_exact_hls_content_can_be_adopted(self):
        good = {"player_state": "PLAYING", "content_id": self.URL, "title": "Film"}
        self.assertTrue(playback_state.hls_session_matches(good, self.URL, "Film"))
        for value in (
            None, {}, {"player_state": "IDLE", "content_id": self.URL},
            {"player_state": "PLAYING", "title": "Film"},
            {"player_state": "PLAYING", "content_id": self.URL, "title": "Another film"},
            {"player_state": "PLAYING", "content_id": self.URL + "?other=1"},
            {"player_state": "PLAYING", "content_id": "http://10.0.0.3:8767/movie.m3u8"},
            {"player_state": "UNKNOWN", "content_id": self.URL},
        ):
            with self.subTest(value=value):
                self.assertFalse(playback_state.hls_session_matches(value, self.URL, "Film"))

    def test_saved_session_adoption_requires_recipient_validation(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / "src" / "cast_control.py").read_text()
        window = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        method = next(node for node in window.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_adopt_session")
        body = ast.get_source_segment(source, method)
        self.assertIn("state.device != self._device()", body)
        self.assertIn("session.recoverable_hls()", body)
        self.assertIn("playback_state.hls_session_matches(", body)
        self.assertIn("if info is not None:", body)


if __name__ == "__main__":
    unittest.main()
