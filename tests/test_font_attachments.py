"""SC-026: extract embedded Matroska font attachments for libass styling."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import font_attachments
import streamer


def _probe_json(*streams: dict) -> str:
    return json.dumps({"streams": list(streams)})


def _attachment(index: int, filename: str, mimetype: str = "") -> dict:
    tags = {"filename": filename}
    if mimetype:
        tags["mimetype"] = mimetype
    return {"index": index, "codec_type": "attachment", "tags": tags}


class ListFontsTests(unittest.TestCase):
    def test_font_attachments_are_listed_in_stream_order(self):
        payload = _probe_json(
            {"index": 0, "codec_type": "video"},
            _attachment(1, "DejaVuSans.ttf"),
            _attachment(2, "cover.jpg", "image/jpeg"),
            _attachment(3, "Captions.OTF", "application/x-font-opentype"),
            _attachment(4, "no-extension", "font/ttf"),
        )
        with mock.patch.object(
            font_attachments.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout=payload),
        ):
            fonts = font_attachments.list_fonts(Path("/film.mkv"))
        self.assertEqual([f.index for f in fonts], [1, 3, 4])
        self.assertEqual([f.suffix for f in fonts], [".ttf", ".otf", ".ttf"])
        # Ordinals count every attachment in the container, so the skipped
        # cover image advances the numbering.
        self.assertEqual([f.ordinal for f in fonts], [0, 2, 3])

    def test_non_fonts_and_failed_probes_yield_nothing(self):
        payload = _probe_json(
            _attachment(1, "poster.png", "image/png"),
            _attachment(2, "notes.txt"),
        )
        with mock.patch.object(
            font_attachments.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout=payload),
        ):
            self.assertEqual(font_attachments.list_fonts(Path("/film.mkv")), [])
        with mock.patch.object(
            font_attachments.subprocess, "run",
            return_value=mock.Mock(returncode=1, stdout=""),
        ):
            self.assertEqual(font_attachments.list_fonts(Path("/film.mkv")), [])
        with mock.patch.object(
            font_attachments.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout="{not json"),
        ):
            self.assertEqual(font_attachments.list_fonts(Path("/film.mkv")), [])
        with mock.patch.object(
            font_attachments.subprocess, "run", side_effect=OSError("no ffprobe"),
        ):
            self.assertEqual(font_attachments.list_fonts(Path("/film.mkv")), [])


def _fake_ffmpeg(payload: str, font_bytes: bytes):
    """Dispatch ffprobe to *payload* and ffmpeg to a written *font_bytes*."""

    def fake_run(command, **_kwargs):
        if "ffprobe" in command[0]:
            return mock.Mock(returncode=0, stdout=payload)
        destination = Path(command[command.index("-dump_attachment:t:0") + 1])
        destination.write_bytes(font_bytes)
        return mock.Mock(returncode=0, stdout="")

    return fake_run


class PrepareFontsTests(unittest.TestCase):
    def test_valid_fonts_are_extracted_into_a_private_directory(self):
        payload = _probe_json(_attachment(1, "DejaVuSans.ttf"))
        with TemporaryDirectory() as folder:
            parent = Path(folder)
            source = parent / "film.mkv"
            source.write_bytes(b"mkv")
            with mock.patch.object(
                font_attachments.subprocess, "run",
                side_effect=_fake_ffmpeg(payload, b"\x00\x01\x00\x00" + b"font" * 4),
            ):
                directory = font_attachments.prepare_fonts(source, parent, "abc123")
            self.assertIsNotNone(directory)
            assert directory is not None
            self.assertTrue(directory.is_dir())
            self.assertEqual([p.name for p in directory.iterdir()], ["font-1.ttf"])
            font_attachments.cleanup_fonts(directory)
            self.assertFalse(directory.exists())

    def test_invalid_or_oversize_fonts_are_rejected(self):
        for payload_bytes in (b"not a font", b"\x00\x01\x00\x00" + b"x" * font_attachments.MAX_FONT_BYTES):
            with self.subTest(size=len(payload_bytes)):
                payload = _probe_json(_attachment(1, "DejaVuSans.ttf"))
                with TemporaryDirectory() as folder:
                    parent = Path(folder)
                    source = parent / "film.mkv"
                    source.write_bytes(b"mkv")
                    with mock.patch.object(
                        font_attachments.subprocess, "run",
                        side_effect=_fake_ffmpeg(payload, payload_bytes),
                    ):
                        self.assertIsNone(
                            font_attachments.prepare_fonts(source, parent, "abc123"))

    def test_cleanup_ignores_missing_directory(self):
        font_attachments.cleanup_fonts(None)
        font_attachments.cleanup_fonts(Path("/does/not/exist"))


class FilterArgsTests(unittest.TestCase):
    def test_fontsdir_is_passed_for_embedded_text_subtitles(self):
        fonts = Path("/tmp/fonts's:demo")
        args = streamer.Session()._filter_args(
            True, None, True, 1.0,
            embedded_subtitle_index=2,
            embedded_source=Path("/film.mkv"),
            fonts_dir=fonts,
        )
        joined = " ".join(args)
        self.assertIn("fontsdir=", joined)
        self.assertIn(streamer.Session._filter_path(fonts), joined)

    def test_no_fontsdir_without_fonts(self):
        args = streamer.Session()._filter_args(
            True, None, True, 1.0,
            embedded_subtitle_index=2,
            embedded_source=Path("/film.mkv"),
        )
        self.assertNotIn("fontsdir=", " ".join(args))


class StartTranscodeFontsTests(unittest.TestCase):
    def test_embedded_text_extracts_fonts_and_stop_cleans_them(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            media = streamer.MediaInfo(
                path=root / "film.mkv", duration=60.0, pix_fmt="yuv420p",
                width=1280, height=720,
                subtitle_tracks=[streamer.SubtitleTrack(2, "ass", "eng")],
            )
            media.path.write_bytes(b"mkv")
            fonts = root / "fonts-test"
            fonts.mkdir()
            session = streamer.Session()
            session.used_software_fallback = False
            proc = mock.MagicMock(pid=1)
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "f.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "p.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen, \
                 mock.patch.object(font_attachments, "prepare_fonts", return_value=fonts) as prepare, \
                 mock.patch.object(font_attachments, "cleanup_fonts") as cleanup:
                session.start_transcode(
                    media, 0.0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None,
                    burn_subs=False, title="Film", embedded_subtitle_index=2,
                )
                prepare.assert_called_once()
                self.assertEqual(prepare.call_args.args[0], media.path)
                args = popen.call_args_list[0].args[0]
                self.assertIn("fontsdir=", " ".join(args))
                session.stop("TV", send_stop=False)
            cleanup.assert_called_with(fonts)


if __name__ == "__main__":
    unittest.main()
