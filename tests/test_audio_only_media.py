"""Audio-only queue probe, preflight and HLS encoder regressions."""
from __future__ import annotations

from pathlib import Path
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import preflight
import reliability_metrics
import server as hls_server
import streamer
from fakecast.receiver import CastMessage, FakeCastReceiver, NS_MEDIA
from playback_state import next_media
from gui_source import main_window_methods


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioOnlyMediaTests(unittest.TestCase):
    def make_fixture(self, path: Path, codec: str) -> None:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2.2", "-vn", "-c:a", codec,
             "-y", str(path)], check=True, capture_output=True, timeout=20,
        )

    def test_media_probe_reads_case_insensitive_music_tags_and_track_totals(self):
        media = streamer.MediaInfo(Path("song.flac"))
        streamer._read_probe(media, {"format": {"duration": "12.5", "tags": {
            "TITLE": "  Song title ", "ARTIST": " Artist ", "ALBUM": " Record ",
            "TRACK": "3/12", "DISCNUMBER": "2/2",
        }}, "streams": [{"codec_type": "audio", "codec_name": "flac",
                        "channels": 2, "channel_layout": "stereo"}]})

        self.assertEqual((media.title, media.artist, media.album),
                         ("Song title", "Artist", "Record"))
        self.assertEqual((media.track_number, media.disc_number), (3, 2))
        self.assertEqual(media.duration, 12.5)

    def test_ffprobe_reads_embedded_music_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "track.mp3"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=0.5", "-metadata", "title=Song title",
                 "-metadata", "artist=Artist", "-metadata", "album=Album",
                 "-metadata", "track=3/12", "-metadata", "disc=2/2",
                 "-c:a", "libmp3lame", "-y", str(path)],
                check=True, capture_output=True, timeout=20,
            )

            media = streamer.ffprobe(path)

        self.assertEqual((media.title, media.artist, media.album),
                         ("Song title", "Artist", "Album"))
        self.assertEqual((media.track_number, media.disc_number), (3, 2))

    def test_mp3_flac_and_aac_are_probeable_as_audio_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = (("track.mp3", "libmp3lame", "mp3"),
                        ("track.flac", "flac", "flac"),
                        ("track.m4a", "aac", "aac"),
                        ("track-vorbis.ogg", "libvorbis", "vorbis"),
                        ("track-opus.ogg", "libopus", "opus"),
                        ("track.wav", "pcm_s16le", "pcm_s16le"),
                        ("track.aiff", "pcm_s16be", "pcm_s16be"))
            for name, encoder, expected_codec in fixtures:
                with self.subTest(name=name):
                    path = root / name
                    self.make_fixture(path, encoder)
                    media = streamer.ffprobe(path)
                    self.assertTrue(media.is_audio_only)
                    self.assertFalse(media.has_video)
                    self.assertEqual(media.vcodec, "")
                    self.assertEqual(media.audio_streams[0].codec, expected_codec)
                    self.assertGreater(media.duration, 2.0)
                    self.assertFalse(media.direct_ok)
                    self.assertIn("AAC transcode", media.direct_reason)

    def test_valid_audio_extension_does_not_make_corrupt_bytes_playable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "not-really-audio.mp3"
            path.write_bytes(b"not an MP3, despite the extension")
            with self.assertRaisesRegex(streamer.StreamError, "ffprobe could not read"):
                streamer.ffprobe(path)

    def test_audio_preflight_decodes_selected_track_without_video(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "track.flac"
            self.make_fixture(path, "flac")
            media = streamer.ffprobe(path)
            result = preflight.check_media(media)
            self.assertGreater(result.bytes_rendered, 0)
            self.assertEqual(result.sample_seconds, 0.8)

    def test_audio_hls_plan_maps_audio_and_never_constructs_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "track.flac"
            self.make_fixture(path, "flac")
            media = streamer.ffprobe(path)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.pid = 12345
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(streamer.video_policy, "make_plan") as video_plan, \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None,
                    burn_subs=False, title="Track",
                )
                args = list(popen.call_args_list[0].args[0])
            self.assertIn("-vn", args)
            self.assertEqual(args[args.index("-map") + 1], "0:a:0")
            self.assertEqual(args[args.index("-c:a") + 1], "aac")
            self.assertFalse(any(value == "-c:v" or value.startswith("-vf") for value in args))
            self.assertFalse(any(value.startswith("0:v") for value in args))
            video_plan.assert_not_called()

            # Execute the exact FFmpeg plan against synthetic audio, then let
            # the fake receiver fetch the resulting authenticated HLS playlist
            # and segments through SmoothCast's real HTTP handler.
            subprocess.run(args, cwd=root, check=True, capture_output=True, timeout=30)
            playlist = root / session._playlist_name
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type,codec_name", "-of", "json", str(playlist)],
                check=True, capture_output=True, text=True, timeout=15,
            )
            streams = json.loads(probe.stdout)["streams"]
            self.assertEqual(streams, [{"codec_name": "aac", "codec_type": "audio"}])

            token = session._playlist_name[len("movie-"):].split(".", 1)[0]
            token = token.removesuffix("-fmp4")
            fake_server = ThreadingHTTPServer(
                ("127.0.0.1", 0), hls_server.H,
            )
            with mock.patch.object(hls_server, "ROOT", root):
                hls_server.write_policy(
                    root, hls_server.make_policy("127.0.0.1", token=token),
                )
                serve_thread = threading.Thread(
                    target=fake_server.serve_forever, daemon=True,
                )
                serve_thread.start()
                receiver = FakeCastReceiver()

                class RecordingClient:
                    def __init__(self):
                        self.frames = []

                    def sendall(self, frame):
                        self.frames.append(frame)

                client = RecordingClient()
                request = CastMessage()
                request.protocol_version = CastMessage.CASTV2_1_0
                request.source_id = "sender-0"
                request.destination_id = "receiver-0"
                request.payload_type = CastMessage.STRING
                request.namespace = NS_MEDIA
                url = f"http://127.0.0.1:{fake_server.server_port}/{session._playlist_name}"
                data = {
                    "type": "LOAD",
                    "media": {
                        "contentId": url,
                        "contentType": "application/vnd.apple.mpegurl",
                        "streamType": "BUFFERED",
                    },
                }
                request.payload_utf8 = json.dumps(data)
                try:
                    receiver._handle(client, request, data)
                    deadline = time.monotonic() + 10
                    while not receiver.media_fetch_results and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(receiver.media_fetch_errors)
                    self.assertEqual(len(receiver.media_fetch_results), 1)
                    result = receiver.media_fetch_results[0]
                    self.assertTrue(result.ended)
                    self.assertGreater(result.segment_count, 0)
                    self.assertEqual(result.requests[0]["content_type"],
                                     "application/vnd.apple.mpegurl")
                finally:
                    receiver.stop()
                    fake_server.shutdown()
                    fake_server.server_close()
                    serve_thread.join(timeout=1)
                    session._stop_sampler()

    def test_mixed_music_video_queue_keeps_order_across_audio_items(self):
        queue = ["song.mp3", "album.flac", "film.mkv", "track.m4a"]
        self.assertEqual(
            [next_media(item, queue, repeat_current=False, auto_next=True)
             for item in queue],
            ["album.flac", "film.mkv", "track.m4a", None],
        )

    def test_device_completion_casts_each_mixed_queue_successor(self):
        source = main_window_methods()["_on_finished"]
        namespace = {
            "pathlib": pathlib,
            "playback_state": __import__("playback_state"),
            "reliability_metrics": reliability_metrics,
            "Async": type("Async", (), {
                "run": staticmethod(lambda work, done=None, failed=None, **_kw:
                                     done(work()) if done else work()),
            }),
            "GLib": type("GLib", (), {
                "idle_add": staticmethod(lambda callback: callback()),
            }),
        }
        body = "class Extracted:\n" + "\n".join(
            "    " + line if line else "" for line in source.splitlines()
        )
        exec(compile(body, "<mixed-queue-completion>", "exec"), namespace)
        window = namespace["Extracted"]()
        queue = ["song.mp3", "album.flac", "film.mkv", "track.m4a"]
        window.queue = queue
        window.cfg = {"loop": False, "autonext": True, "loop_all": False}
        window.busy = False
        window.session = None
        window.now_playing = queue[0]
        window._finished_handled = False
        window._device = lambda: "Cast fake"
        window._record_watch = lambda *_args: None
        window._stop_monitor = lambda: None
        window._set_levels_hint = lambda *_args: None
        window._refresh_controls = lambda: None
        window._rebuild_queue = lambda: None
        window._notify = lambda *_args: None
        window.toast = lambda *_args, **_kwargs: None
        window._cast_path = unittest.mock.Mock()

        class EndedSession:
            def stop(self, _device, *, send_stop):
                assert send_stop is False
                return True

        advanced = []
        for current in queue[:-1]:
            window.now_playing = current
            window.session = EndedSession()
            window._on_finished()
            advanced.append(window._cast_path.call_args.args)
        self.assertEqual(
            advanced,
            [(Path(queue[index]), 0.0) for index in range(1, len(queue))],
        )


if __name__ == "__main__":
    unittest.main()
