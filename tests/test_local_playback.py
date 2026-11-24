"""Regression checks for local ffplay playback."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import local_playback
import media_tools


class LocalPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.playback = local_playback.LocalPlayback()
        self._player_patch = None
        self._popen_patch = None
        self._popen_mock = None
        self._isfile_patch = None
        self.proc = None

    def tearDown(self):
        for patcher in (self._popen_patch, self._player_patch, self._isfile_patch):
            if patcher is not None:
                patcher.stop()

    def _start(self, path="movie.mp4"):
        self._player_patch = mock.patch.object(
            media_tools.shutil, "which", return_value="/usr/bin/ffplay"
        )
        self._player_patch.start()
        self._isfile_patch = mock.patch.object(local_playback.Path, "is_file", return_value=True)
        self._isfile_patch.start()
        self.proc = mock.MagicMock()
        self.proc.poll.return_value = None
        self._popen_patch = mock.patch.object(
            local_playback.subprocess, "Popen", return_value=self.proc
        )
        self._popen_mock = self._popen_patch.start()
        self.playback.start(path)
        return self.proc

    def test_inactive_before_start(self):
        self.assertFalse(self.playback.is_active())

    def test_available_when_ffplay_installed(self):
        patcher = mock.patch.object(media_tools.shutil, "which", return_value="/usr/bin/ffplay")
        patcher.start()
        try:
            self.assertTrue(self.playback.available())
        finally:
            patcher.stop()

    def test_unavailable_when_ffplay_missing(self):
        patcher = mock.patch.object(media_tools.shutil, "which", return_value=None)
        patcher.start()
        try:
            self.assertFalse(self.playback.available())
        finally:
            patcher.stop()

    def test_start_launches_ffplay(self):
        self._start()
        self.assertTrue(self.playback.is_active())
        args = self._popen_mock.call_args.args[0]
        self.assertEqual(args[0], "/usr/bin/ffplay")
        self.assertIn("-loglevel", args)
        self.assertIn("movie.mp4", args)

    def test_start_accepts_audio_only_queue_item(self):
        self._start("song.flac")
        args = self._popen_mock.call_args.args[0]
        self.assertEqual(args[-1], "song.flac")

    def test_start_rejects_missing_file(self):
        patcher = mock.patch.object(media_tools.shutil, "which", return_value="/usr/bin/ffplay")
        patcher.start()
        try:
            with self.assertRaises(FileNotFoundError):
                self.playback.start("/nonexistent/movie.mp4")
        finally:
            patcher.stop()
        self.assertFalse(self.playback.is_active())

    def test_start_rejects_missing_ffplay(self):
        patcher = mock.patch.object(media_tools.shutil, "which", return_value=None)
        patcher.start()
        try:
            with self.assertRaises(FileNotFoundError):
                self.playback.start("movie.mp4")
        finally:
            patcher.stop()
        self.assertFalse(self.playback.is_active())

    def test_start_while_active_is_noop(self):
        self._start("movie.mp4")
        # Already active: a second start must not spawn another process.
        self.playback.start("other.mp4")
        self.assertEqual(self._popen_mock.call_count, 1)

    def test_stop_terminates_process(self):
        self._start()
        self.playback.stop()
        self.proc.terminate.assert_called_once()
        self.proc.wait.assert_called_once()
        self.assertFalse(self.playback.is_active())
        self.assertIsNone(self.playback.proc)

    def test_stop_reaps_process_after_terminate_timeout(self):
        self._start()
        self.proc.wait.side_effect = [
            local_playback.subprocess.TimeoutExpired("ffplay", 4), 0
        ]
        self.playback.stop()
        self.proc.terminate.assert_called_once()
        self.proc.kill.assert_called_once()
        self.assertEqual(self.proc.wait.call_count, 2)
        self.assertIsNone(self.playback.proc)

    def test_stop_reaps_already_exited_process_without_signalling(self):
        self._start()
        self.proc.poll.return_value = 0
        self.playback.stop()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        self.proc.wait.assert_called_once()
        self.assertIsNone(self.playback.proc)

    def test_stop_when_inactive_is_noop(self):
        self.playback.stop()
        self.assertFalse(self.playback.is_active())

    def test_is_active_false_after_process_exits(self):
        self._start()
        self.assertTrue(self.playback.is_active())
        self.proc.poll.return_value = 0
        self.assertFalse(self.playback.is_active())


if __name__ == "__main__":
    unittest.main()
