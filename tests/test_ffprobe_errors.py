"""ffprobe() must report every failure as a StreamError, never leak subprocess
or JSON exceptions to its callers (issue #234).

Callers rely on StreamError text: cast attempts surface it through
``_cast_failed``/``toast``/``_console`` in ``cast_session.py``, and queue
duration probes deliberately degrade a failing item to a zero duration in
``queue_metadata.inspect``.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import streamer

MEDIA = pathlib.Path("/films/a.mkv")


def completed(stdout: str, returncode: int = 0):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr="")


class FfprobeErrorTests(unittest.TestCase):
    def probe(self, **run_kwargs) -> streamer.StreamError:
        with mock.patch.object(streamer.subprocess, "run", **run_kwargs):
            with self.assertRaises(streamer.StreamError) as caught:
                streamer.ffprobe(MEDIA)
        return caught.exception

    def test_missing_binary_is_reported(self):
        error = self.probe(side_effect=FileNotFoundError())
        self.assertIn("not installed or not on PATH", str(error))
        self.assertIsInstance(error.__cause__, FileNotFoundError)

    def test_timeout_is_reported(self):
        error = self.probe(side_effect=subprocess.TimeoutExpired("ffprobe", 30))
        self.assertIn("timed out while reading this file", str(error))
        self.assertIsInstance(error.__cause__, subprocess.TimeoutExpired)

    def test_spawn_failure_is_reported(self):
        error = self.probe(side_effect=OSError("Exec format error"))
        self.assertIn("could not be started", str(error))
        self.assertIn("Exec format error", str(error))

    def test_non_zero_exit_is_reported(self):
        error = self.probe(return_value=completed("", returncode=1))
        self.assertEqual(str(error), "ffprobe could not read this file")

    def test_unreadable_json_is_reported(self):
        error = self.probe(return_value=completed("not json at all"))
        self.assertIn("unusable data for this file", str(error))
        self.assertIsInstance(error.__cause__, ValueError)

    def test_non_object_json_is_reported(self):
        error = self.probe(return_value=completed("[]"))
        self.assertIn("unusable data for this file", str(error))

    def test_each_failure_mode_has_its_own_message(self):
        messages = {
            str(self.probe(side_effect=FileNotFoundError())),
            str(self.probe(side_effect=subprocess.TimeoutExpired("ffprobe", 30))),
            str(self.probe(return_value=completed("not json"))),
            str(self.probe(return_value=completed("", returncode=1))),
        }
        self.assertEqual(len(messages), 4)

    def test_valid_metadata_is_still_parsed(self):
        payload = json.dumps({
            "format": {"duration": "12.5", "bit_rate": "1500000"},
            "streams": [{
                "index": 0, "codec_type": "video", "codec_name": "h264",
                "profile": "High", "width": 1920, "height": 1080,
                "disposition": {"attached_pic": 0},
            }],
        })
        with mock.patch.object(streamer.subprocess, "run",
                               return_value=completed(payload)):
            media = streamer.ffprobe(MEDIA)
        self.assertEqual(media.duration, 12.5)
        self.assertEqual(media.bitrate, 1500000)
        self.assertEqual(media.vcodec, "h264")

    def test_cancellable_probe_stops_its_child_promptly(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(streamer.StreamError) as caught:
                streamer._ffprobe_cancellable(
                    [sys.executable, "-c", "import time; time.sleep(10)"], cancel,
                )
        finally:
            timer.cancel()
        self.assertIn("prewarm cancelled", str(caught.exception))
        self.assertLess(time.monotonic() - started, 3)

    def test_cancellable_probe_enforces_its_timeout(self):
        started = time.monotonic()
        with self.assertRaises(streamer.StreamError) as caught:
            streamer._ffprobe_cancellable(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                threading.Event(), timeout=0.1,
            )
        self.assertIn("timed out", str(caught.exception))
        self.assertLess(time.monotonic() - started, 3)

    def test_cover_art_only_file_still_reports_its_own_error(self):
        payload = json.dumps({
            "format": {"duration": "0"},
            "streams": [{
                "index": 0, "codec_type": "video", "codec_name": "mjpeg",
                "disposition": {"attached_pic": 1},
            }],
        })
        error = self.probe(return_value=completed(payload))
        self.assertIn("No motion-video stream", str(error))


if __name__ == "__main__":
    unittest.main()
