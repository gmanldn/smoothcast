"""P0 audio stream selection: MKV metadata, GUI routing and HLS persistence."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer

ROOT = Path(__file__).resolve().parents[1]

from gui_source import combined_source


class AudioTrackTests(unittest.TestCase):
    def media(self, root: Path) -> streamer.MediaInfo:
        return streamer.MediaInfo(
            path=root / "multilingual.mkv", duration=180.0,
            pix_fmt="yuv420p", width=1280, height=720,
            audio_tracks=2,
            audio_streams=[
                streamer.AudioTrack(0, "aac", 2, "eng", "English stereo", "stereo"),
                streamer.AudioTrack(1, "eac3", 6, "fra", "French surround", "5.1", True),
            ],
        )

    def test_ffprobe_enumerates_language_commentary_channels_and_default(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "film.mkv"
            path.touch()
            payload = {
                "format": {"duration": "120.5"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264",
                     "width": 1920, "height": 1080},
                    {"codec_type": "audio", "codec_name": "aac",
                     "channels": 2, "channel_layout": "stereo",
                     "tags": {"language": "eng", "title": "Main"}},
                    {"codec_type": "audio", "codec_name": "eac3",
                     "channels": 6, "channel_layout": "5.1",
                     "tags": {"language": "jpn", "title": "Director commentary"},
                     "disposition": {"default": 1}},
                ],
            }
            completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
            with mock.patch.object(streamer.subprocess, "run", return_value=completed):
                media = streamer.ffprobe(path)
        self.assertEqual(media.audio_tracks, 2)
        self.assertEqual([t.index for t in media.audio_streams], [0, 1])
        self.assertEqual(streamer.preferred_audio_track(media).index, 1)
        self.assertEqual(streamer.preferred_audio_track(media, 0).index, 0)
        self.assertIsNone(streamer.preferred_audio_track(media, 99))
        self.assertIn("JPN", media.audio_streams[1].label)
        self.assertIn("Director commentary", media.audio_streams[1].label)
        self.assertIn("5.1", media.audio_streams[1].label)

    def test_fallback_default_and_silent_movies(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            media.audio_streams[1] = streamer.AudioTrack(
                1, "eac3", 6, "fra", "French surround", "5.1", False
            )
            self.assertEqual(streamer.preferred_audio_track(media).index, 0)
            media.audio_streams.clear()
            self.assertIsNone(streamer.preferred_audio_track(media))

    def test_explicit_audio_map_and_session_save(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            media = self.media(root)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.pid = 12345
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 71.5, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None,
                    burn_subs=False, title="Film", audio_track_index=1,
                )
            ffmpeg_args = popen.call_args_list[0].args[0]
            self.assertEqual(ffmpeg_args[ffmpeg_args.index("-map", ffmpeg_args.index("-i"))+3], "0:a:1")
            self.assertEqual(session.state.audio_track_index, 1)
            self.assertEqual(session.state.offset, 71.5)

    def test_invalid_explicit_index_does_not_start_an_encoder(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            session = streamer.Session()
            with mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(streamer.subprocess, "Popen") as popen, \
                 mock.patch.object(session, "_start_server") as server:
                with self.assertRaisesRegex(streamer.StreamError, "unavailable"):
                    session.start_transcode(
                        media, 0, device="TV", quality="balanced",
                        audio_profile="original", subs_file=None,
                        burn_subs=False, title="Film", audio_track_index=42,
                    )
            popen.assert_not_called()
            server.assert_not_called()

    def test_software_fallback_keeps_explicit_audio_mapping(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            media = self.media(root)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.pid = 12345
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", side_effect=[False, True]), \
                 mock.patch.object(streamer, "_terminate"), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 15.0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None,
                    burn_subs=False, title="Film", audio_track_index=1,
                )
            self.assertEqual(popen.call_count, 3)
            for encoder in popen.call_args_list[:2]:
                self.assertIn("0:a:1", encoder.args[0])
            self.assertEqual(session.state.audio_track_index, 1)

    def test_ui_carries_selection_through_cast_restart_and_previews(self):
        source = combined_source()
        self.assertIn('"audio_track_by_file": {}', source)
        self.assertIn('self.audio_track_dropdown = dropdown_row(', source)
        self.assertIn('self._update_audio_choices(media)', source)
        self.assertIn('audio_track_index=audio_track', source)
        self.assertIn('audio_track_override=choice', source)
        self.assertIn('state.audio_track_index if state else -1', source)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg needed for real two-track trim checks")
class SelectedTrackTrimTests(unittest.TestCase):
    """SC-066 #75: measurement and encoded gain must follow the chosen track."""

    def test_loud_and_quiet_tracks_measure_and_trim_independently(self):
        with TemporaryDirectory() as folder:
            media = Path(folder) / "two-tracks.mka"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
                    "-filter_complex", "[0:a]volume=8[a0];[1:a]volume=0.05[a1]",
                    "-map", "[a0]", "-map", "[a1]",
                    "-c:a", "aac", str(media),
                ],
                check=True, capture_output=True, timeout=60,
            )
            loud = streamer.measure_mean_volume(str(media), audio_track_index=0)
            quiet = streamer.measure_mean_volume(str(media), audio_track_index=1)
            self.assertIsNotNone(loud)
            self.assertIsNotNone(quiet)
            self.assertGreater(loud - quiet, 12.0)

            loud_trim = streamer.auto_trim_gain(str(media), "dialogue", audio_track_index=0)
            quiet_trim = streamer.auto_trim_gain(str(media), "dialogue", audio_track_index=1)
            self.assertLess(loud_trim, quiet_trim)

            loud_chain = streamer.effective_chain(str(media), "dialogue", audio_track_index=0)
            quiet_chain = streamer.effective_chain(str(media), "dialogue", audio_track_index=1)
            self.assertTrue(loud_chain[0].startswith("volume=-"), loud_chain[0])
            self.assertTrue(quiet_chain[0].startswith("volume="), quiet_chain[0])
            self.assertNotIn("-", quiet_chain[0])

            self.assertEqual(
                streamer.effective_chain(str(media), "original", audio_track_index=0), [],
            )


if __name__ == "__main__":
    unittest.main()
