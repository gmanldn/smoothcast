"""End-to-end media matrix (SC-012 #19).

Generate tiny synthetic fixtures across containers and codecs (H.264/HEVC/VP9/
AV1 video; AAC/AC-3/DTS/Opus audio; 8/10-bit; multiple streams; sidecar
subtitles) and assert (a) the direct-vs-transcode decision and (b) that the real
transcode output is receiver-safe H.264 / 8-bit 4:2:0 / AAC. Local, headless and
bounded; each case skips when its FFmpeg encoder is unavailable.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamer

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _encoders() -> set[str]:
    if not FFMPEG:
        return set()
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0][:1] in "VAS" and "." in parts[0]:
            names.add(parts[1])
    return names


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=120)


def _probe(path: pathlib.Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    ).stdout
    return json.loads(out or "{}")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg/FFprobe required")
class MediaMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoders = _encoders()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _require(self, *names):
        missing = [name for name in names if name not in self.encoders]
        if missing:
            self.skipTest(f"missing FFmpeg encoders: {missing}")

    def _make(self, name, vcodec_args, *, pix_fmt=None, acodec="aac",
              audio_extra=None):
        path = self.work / name
        args = [
            FFMPEG, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc=size=128x96:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            *vcodec_args,
        ]
        if pix_fmt:
            args += ["-pix_fmt", pix_fmt]
        if acodec == "none":
            args += ["-an"]
        else:
            args += ["-c:a", acodec]
            if audio_extra:
                args += audio_extra
        args += ["-t", "1", "-shortest", str(path)]
        _run(args)
        return path

    def _assert_transcode_output(self, source: pathlib.Path) -> None:
        # Use the transcoder's real output constraints, then verify the bytes.
        video = streamer.Session()._codec_args("balanced", True)
        self.assertIn("libx264", video)
        self.assertIn("yuv420p", video)
        out = self.work / "out.mp4"
        _run([FFMPEG, "-hide_banner", "-y", "-i", str(source), *video,
              "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-t", "1", str(out)])
        streams = _probe(out)["streams"]
        video_stream = next(s for s in streams if s["codec_type"] == "video")
        audio_stream = next(s for s in streams if s["codec_type"] == "audio")
        self.assertEqual(video_stream["codec_name"], "h264")
        self.assertEqual(video_stream["pix_fmt"], "yuv420p")
        self.assertEqual(video_stream.get("profile"), "High")
        self.assertEqual(audio_stream["codec_name"], "aac")

    def test_direct_playable_h264_aac_mp4(self):
        self._require("libx264", "aac")
        path = self._make(
            "direct.mp4", ["-c:v", "libx264", "-preset", "ultrafast"],
            pix_fmt="yuv420p",
        )
        media = streamer.ffprobe(path)
        self.assertTrue(media.direct_ok, media.direct_reason)
        self.assertEqual(media.vcodec, "h264")
        self.assertEqual(media.acodec, "aac")

    def test_hevc_vp9_av1_transcode_to_receiver_safe_h264(self):
        cases = [
            ("hevc.mkv", "libx265",
             ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error"]),
            ("vp9.mkv", "libvpx-vp9",
             ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"]),
            ("av1.mkv", "libsvtav1", ["-c:v", "libsvtav1", "-preset", "12"]),
        ]
        for name, encoder, vcodec_args in cases:
            with self.subTest(codec=encoder):
                self._require(encoder, "aac")
                path = self._make(name, vcodec_args)
                media = streamer.ffprobe(path)
                self.assertFalse(media.direct_ok)
                self.assertIn("transcod", media.direct_reason.lower())
                self._assert_transcode_output(path)

    def test_ten_bit_h264_needs_transcode(self):
        self._require("libx264", "aac")
        try:
            path = self._make(
                "tenbit.mkv",
                ["-c:v", "libx264", "-preset", "ultrafast"],
                pix_fmt="yuv420p10le",
            )
        except subprocess.CalledProcessError:
            self.skipTest("libx264 build lacks 10-bit support")
        media = streamer.ffprobe(path)
        self.assertEqual(media.pix_fmt, "yuv420p10le")
        self.assertFalse(media.direct_ok)
        self._assert_transcode_output(path)

    def test_non_aac_audio_needs_transcode(self):
        self._require("libx264", "aac")
        for name, acodec, extra in (
            ("ac3.mkv", "ac3", None),
            ("dts.mkv", "dca", ["-strict", "-2"]),
            ("opus.mkv", "libopus", None),
        ):
            with self.subTest(audio=acodec):
                self._require(acodec)
                path = self._make(
                    name, ["-c:v", "libx264", "-preset", "ultrafast"],
                    acodec=acodec, audio_extra=extra,
                )
                media = streamer.ffprobe(path)
                self.assertFalse(media.direct_ok)

    def test_multiple_audio_streams_and_sidecar_subtitle(self):
        self._require("libx264", "aac", "ac3")
        path = self.work / "multi.mkv"
        _run([
            FFMPEG, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc=size=128x96:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a:0", "aac", "-c:a:1", "ac3",
            "-t", "1", "-shortest", str(path),
        ])
        media = streamer.ffprobe(path)
        self.assertGreaterEqual(len(media.audio_streams), 2)
        self.assertFalse(media.direct_ok)

        video = self.work / "film.mp4"
        _run([FFMPEG, "-hide_banner", "-y",
              "-f", "lavfi", "-i", "testsrc=size=128x96:rate=10",
              "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", str(video)])
        sidecar = self.work / "film.srt"
        sidecar.write_text("1\n00:00:00,000 --> 00:00:00,900\nHi\n", encoding="utf-8")
        self.assertEqual(streamer.find_subtitles(video), sidecar.resolve())


if __name__ == "__main__":
    unittest.main()
