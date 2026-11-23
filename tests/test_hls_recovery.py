"""GTK-free HLS finalisation, resumed casting and receiver-ownership safety."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gui_source import main_window_methods

import playback_state
import streamer


class HlsRecoveryTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.root = Path(home.name)
        patch = mock.patch.object(streamer, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def playlist(self, *, complete=True, segment_bytes=b"ts", segment_name="segment-00000.ts"):
        (self.root / segment_name).write_bytes(segment_bytes)
        entries = [
            "#EXTM3U", "#EXT-X-TARGETDURATION:4",
            "#EXTINF:2.000,", segment_name,
        ]
        if complete:
            entries.append("#EXT-X-ENDLIST")
        (self.root / streamer.HLS_NAME).write_text(
            "\n".join(entries) + "\n", encoding="utf-8",
        )

    def saved(self):
        session = streamer.Session()
        session.state = streamer.SessionState(
            file="/movie.mkv", mode="transcode", offset=0.0,
            duration=2.0, device="TV", title="Film",
            stream_url="http://192.168.1.10:8767/movie.m3u8",
        )
        return session

    def test_finalized_one_segment_can_outlive_encoder(self):
        self.playlist()
        session = self.saved()
        proc = mock.Mock()
        proc.poll.return_value = -1
        session.ffmpeg = proc
        self.assertFalse(session.active())
        with mock.patch.object(streamer, "_server_healthy", return_value=True):
            self.assertTrue(session.recoverable_hls())

    def test_dead_or_missing_http_server_prevents_recovery(self):
        self.playlist()
        session = self.saved()
        with mock.patch.object(streamer, "_server_healthy", return_value=False):
            self.assertFalse(session.recoverable_hls())

    def test_unfinalized_or_missing_or_empty_segments_prevent_recovery(self):
        session = self.saved()
        with mock.patch.object(streamer, "_server_healthy", return_value=True):
            self.playlist(complete=False)
            self.assertFalse(session.recoverable_hls())
            self.playlist()
            (self.root / "segment-00000.ts").unlink()
            self.assertFalse(session.recoverable_hls())
            self.playlist(segment_bytes=b"")
            self.assertFalse(session.recoverable_hls())

    def test_hls_playlist_must_not_load_another_file(self):
        session = self.saved()
        with mock.patch.object(streamer, "_server_healthy", return_value=True):
            self.playlist(segment_name="../film.ts")
            self.assertFalse(session.recoverable_hls())
            outside = str((self.root.parent / "outside-segment.ts").resolve())
            self.playlist(segment_name=outside)
            self.assertFalse(session.recoverable_hls())

    def test_live_encoder_still_uses_normal_active_path(self):
        session = self.saved()
        proc = mock.Mock()
        proc.poll.return_value = None
        session.ffmpeg = proc
        self.assertTrue(session.active())
        self.assertFalse(session.recoverable_hls())


class OwnershipTests(unittest.TestCase):
    URL = "http://192.168.1.10:8767/movie.m3u8"

    def test_saved_hls_url_and_optional_title_must_match(self):
        good = {"player_state": "PLAYING", "content_id": self.URL, "title": "Film"}
        self.assertTrue(playback_state.hls_session_matches(good, self.URL, "Film"))
        self.assertTrue(playback_state.hls_session_matches(
            {"player_state": "PAUSED", "content_id": self.URL}, self.URL, "Film",
        ))
        for value in (
            None, {}, {"player_state": "IDLE", "content_id": self.URL},
            {"player_state": "PLAYING", "title": "Film"},
            {"player_state": "PLAYING", "content_id": self.URL, "title": "Other"},
            {"player_state": "PLAYING", "content_id": self.URL + "?replaced=1"},
            {"player_state": "PLAYING", "content_id": "http://192.168.1.3:8767/movie.m3u8"},
            {"player_state": "OFFLINE", "content_id": self.URL},
        ):
            with self.subTest(value=value):
                self.assertFalse(playback_state.hls_session_matches(value, self.URL, "Film"))

    def test_gui_ownership_is_validated_in_worker_before_adoption(self):
        text = main_window_methods()["_adopt_session"]
        self.assertIn("state.device != self._device()", text)
        self.assertIn("session.recoverable_hls()", text)
        self.assertIn("playback_state.hls_session_matches(", text)
        self.assertIn("if info is not None:", text)


if __name__ == "__main__":
    unittest.main()
