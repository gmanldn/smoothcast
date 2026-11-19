"""P0 #16: subtitle text encoding, private staging and sender integration."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer
import subtitle_encoding


CAPTION = "1\n00:00:00,000 --> 00:00:01,000\nCafé déjà vu\n"


class SubtitleEncodingTests(unittest.TestCase):
    def test_utf8_and_utf8_bom_round_trip(self):
        for codec in ("utf-8", "utf-8-sig"):
            with self.subTest(codec=codec):
                output, detected = subtitle_encoding.decode_srt(CAPTION.encode(codec))
                self.assertEqual(detected, codec)
                self.assertEqual(output.decode("utf-8"), CAPTION)

    def test_utf16_bom_both_endiannesses_and_without_bom(self):
        for codec in ("utf-16", "utf-16-le", "utf-16-be"):
            with self.subTest(codec=codec):
                raw = CAPTION.encode(codec)
                output, detected = subtitle_encoding.decode_srt(raw)
                self.assertEqual(output.decode("utf-8"), CAPTION)
                self.assertEqual(detected, codec)

    def test_legacy_windows_1252_preserves_accents(self):
        output, detected = subtitle_encoding.decode_srt(CAPTION.encode("cp1252"))
        self.assertEqual(detected, "cp1252")
        self.assertEqual(output.decode("utf-8"), CAPTION)

    def test_normalises_crlf_and_cr_without_touching_text(self):
        raw = CAPTION.replace("\n", "\r\n").encode("utf-16")
        output, _ = subtitle_encoding.decode_srt(raw)
        self.assertEqual(output, CAPTION.encode("utf-8"))

    def test_rejects_empty_truncated_binary_damaged_utf16_and_excess(self):
        invalid = [
            b"", b"\x00\x01\x02", b"not SRT text",
            b"\xff\xfe\x31", b"\x81\x81",
            b"1\n00:00:00,000 --> 00:00:01,000\n\x00NO\n",
            b"0" * (subtitle_encoding.MAX_SUBTITLE_BYTES + 1),
        ]
        for raw in invalid:
            with self.subTest(raw=raw[:24]), self.assertRaises(subtitle_encoding.SubtitleEncodingError):
                subtitle_encoding.decode_srt(raw)

    def test_atomic_private_staging_and_original_is_unchanged(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "movie.srt"
            private = root / "private" / "receiver_subs.srt"
            original = CAPTION.encode("utf-16-le")
            source.write_bytes(original)
            target, encoding = subtitle_encoding.stage_srt(source, private)
            self.assertEqual(encoding, "utf-16-le")
            self.assertEqual(target, private)
            self.assertEqual(target.read_bytes(), CAPTION.encode("utf-8"))
            self.assertEqual(source.read_bytes(), original)
            if os.name != "nt":
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            source.write_bytes(b"not an SRT")
            with self.assertRaises(subtitle_encoding.SubtitleEncodingError):
                subtitle_encoding.stage_srt(source, private)
            self.assertEqual(private.read_bytes(), CAPTION.encode("utf-8"))
            self.assertFalse(list(private.parent.glob(".smoothcast-srt-*")))

    def test_rejects_large_source_before_copying(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "oversize.srt"
            with source.open("wb") as handle:
                handle.truncate(subtitle_encoding.MAX_SUBTITLE_BYTES + 1)
            destination = root / "private" / "sub.srt"
            with self.assertRaisesRegex(subtitle_encoding.SubtitleEncodingError, "16 MiB"):
                subtitle_encoding.stage_srt(source, destination)
            self.assertFalse(destination.exists())


class SubtitleSenderIntegrationTests(unittest.TestCase):
    def test_direct_cast_receives_private_utf8_and_keeps_original_state_path(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "captions.srt"
            source.write_bytes(CAPTION.encode("utf-16"))
            media = streamer.MediaInfo(path=root / "video.mp4", duration=50)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.poll.return_value = 0
            proc.returncode = 0
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_direct(
                    media, device="TV", subs_file=source,
                    subs_disabled=False, title="Film",
                )
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index("-s") + 1], str(root / "receiver_subs.srt"))
            self.assertEqual((root / "receiver_subs.srt").read_bytes(), CAPTION.encode("utf-8"))
            self.assertEqual(session.state.subs, str(source))

    def test_transcode_external_receiver_and_burn_in_both_normalise_srt(self):
        for burn in (False, True):
            with self.subTest(burn=burn), TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "captions.srt"
                source.write_bytes(CAPTION.encode("cp1252"))
                media = streamer.MediaInfo(
                    path=root / "video.mkv", duration=50.0,
                    pix_fmt="yuv420p", width=1280, height=720,
                )
                session = streamer.Session()
                proc = mock.MagicMock()
                proc.pid = 12345
                proc.poll.return_value = None
                with mock.patch.object(streamer, "ROOT", root), \
                     mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                     mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                     mock.patch.object(streamer, "host_ip", return_value="192.168.1.7"), \
                     mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                     mock.patch.object(streamer, "_save_session"), \
                     mock.patch.object(session, "_start_server"), \
                     mock.patch.object(session, "_wait_for_segments", return_value=True), \
                     mock.patch.object(streamer.time, "sleep"), \
                     mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                    session.start_transcode(
                        media, 12, device="TV", quality="balanced",
                        audio_profile="original", subs_file=source,
                        burn_subs=burn, title="Film",
                    )
                media_path = root / ("burned_subs.srt" if burn else "receiver_subs.srt")
                self.assertEqual(media_path.read_bytes(), CAPTION.encode("utf-8"))
                caster_args = popen.call_args_list[-1].args[0]
                if burn:
                    self.assertIn("--no-subs", caster_args)
                    self.assertIn("subtitles=filename=burned_subs.srt",
                                  " ".join(popen.call_args_list[0].args[0]))
                else:
                    self.assertEqual(caster_args[caster_args.index("-s") + 1],
                                     str(media_path))
                self.assertEqual(session.state.subs, str(source))
                self.assertEqual(source.read_bytes(), CAPTION.encode("cp1252"))

    def test_failed_srt_does_not_spawn_cast_process(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "broken.srt"
            source.write_bytes(b"garbled")
            media = streamer.MediaInfo(path=root / "video.mp4", duration=50)
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(streamer.StreamError, "timestamp"):
                    streamer.Session().start_direct(
                        media, device="TV", subs_file=source,
                        subs_disabled=False, title="Film",
                    )
            popen.assert_not_called()

    def test_ffmpeg_can_burn_normalised_caption_if_libass_is_available(self):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("FFmpeg not installed on this test host")
        filters = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=10,
        )
        if " subtitles " not in filters.stdout:
            self.skipTest("This FFmpeg build does not include the subtitles/libass filter")
        with TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "source.srt"
            original.write_bytes(CAPTION.encode("utf-16"))
            staged, _ = subtitle_encoding.stage_srt(original, root / "staged.srt")
            args = [
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=160x90:r=5:d=0.4",
                "-vf", f"subtitles=filename={staged}", "-frames:v", "1",
                "-f", "null", "-",
            ]
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr[:1000])


if __name__ == "__main__":
    unittest.main()
