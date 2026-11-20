"""SC-023: dialogue-first, clip-safe, LFE-free surround downmix."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import audio_downmix
import streamer

# FFmpeg native channel order, used here as the independent oracle.
NATIVE = {
    "5.0": ["FL", "FR", "FC", "BL", "BR"],
    "5.0(side)": ["FL", "FR", "FC", "SL", "SR"],
    "5.1": ["FL", "FR", "FC", "LFE", "BL", "BR"],
    "5.1(side)": ["FL", "FR", "FC", "LFE", "SL", "SR"],
    "6.1": ["FL", "FR", "FC", "LFE", "BC", "SL", "SR"],
    "6.1(back)": ["FL", "FR", "FC", "LFE", "BL", "BR", "BC"],
    "7.1": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    "quad": ["FL", "FR", "BL", "BR"],
    "quad(side)": ["FL", "FR", "SL", "SR"],
    "4.0": ["FL", "FR", "FC", "BC"],
}


def parse(expr: str) -> dict[str, dict[int, float]]:
    assert expr.startswith("pan=stereo|")
    out = {}
    for part in expr.split("|")[1:]:
        label, terms = part.split("=")
        out[label] = {int(i): float(c) for c, i in
                      (t.split("*c") for t in terms.split("+"))}
    return out


class DownmixPolicyTests(unittest.TestCase):
    def test_unchanged_for_original_stereo_mono_and_unknown_layouts(self):
        f = audio_downmix.downmix_filter
        self.assertIsNone(f(6, "5.1", "original"))
        self.assertIsNone(f(6, "5.1", "nonsense"))
        self.assertIsNone(f(2, "stereo", "dialogue"))
        self.assertIsNone(f(1, "mono", "night"))
        self.assertIsNone(f(0, "", "dialogue"))
        self.assertIsNone(f(6, "", "dialogue"))             # untagged
        self.assertIsNone(f(6, "hexagonal", "dialogue"))    # unknown order
        self.assertIsNone(f(8, "5.1", "dialogue"))          # tag disagrees
        self.assertIsNone(f(True, "5.1", "dialogue"))
        self.assertIsNone(f("6", "5.1", "dialogue"))
        self.assertIsNone(f(None, None, None))

    def test_every_known_layout_is_safe_and_dialogue_first(self):
        for layout, names in NATIVE.items():
            for profile in ("dialogue", "night"):
                with self.subTest(layout=layout, profile=profile):
                    mix = parse(audio_downmix.downmix_filter(
                        len(names), layout, profile))
                    self.assertEqual(set(mix), {"FL", "FR"})
                    for label, taps in mix.items():
                        total = sum(taps.values())
                        self.assertLessEqual(total, 1.0)     # cannot clip
                        self.assertGreater(total, 0.999)     # not quieter
                        for index in taps:
                            self.assertNotEqual(names[index], "LFE")
                            self.assertLess(index, len(names))
                        # Same side only (or the shared centre channels).
                        for index in taps:
                            n = names[index]
                            if n in ("FC", "BC"):
                                continue
                            left = n.endswith("L")
                            self.assertEqual(left, label == "FL", (label, n))
                        centre = [c for i, c in taps.items()
                                  if names[i] in ("FC", "BC")]
                        others = [c for i, c in taps.items()
                                  if names[i] not in ("FC", "BC")]
                        if "FC" in names:
                            self.assertGreater(max(centre), max(others))

    def test_lfe_is_never_mixed_in(self):
        for layout in ("5.1", "5.1(side)", "6.1", "6.1(back)", "7.1"):
            mix = parse(audio_downmix.downmix_filter(
                len(NATIVE[layout]), layout, "dialogue"))
            lfe = NATIVE[layout].index("LFE")
            self.assertTrue(all(lfe not in taps for taps in mix.values()))

    def test_layout_is_case_and_space_tolerant(self):
        self.assertEqual(
            audio_downmix.downmix_filter(6, " 5.1 ", "dialogue"),
            audio_downmix.downmix_filter(6, "5.1", "dialogue"))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class DownmixFfmpegTests(unittest.TestCase):
    """Run the real filter: valid syntax, centre favoured, LFE dropped."""

    @staticmethod
    def run_ffmpeg(*args: str) -> str:
        return subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", *args],
            capture_output=True, text=True, timeout=60, check=True,
        ).stderr

    def source(self, folder: str, name: str, layout_expr: str) -> str:
        path = str(Path(folder) / name)
        self.run_ffmpeg(
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=48000",
            "-af", layout_expr, "-c:a", "pcm_s16le", path,
        )
        return path

    def level(self, path: str, chain: str, *extra: str) -> float:
        text = self.run_ffmpeg("-i", path, *extra, "-af", chain, "-f", "null", "-")
        return float(re.search(r"max_volume: (-?[\d.]+|-inf) dB", text).group(1))

    def test_downmix_preserves_audio_alignment_after_mp4_encoding(self):
        # A white frame and a centre-only tone both begin at 480 ms.
        mix = audio_downmix.downmix_filter(8, "7.1", "dialogue")
        with TemporaryDirectory() as folder:
            output = str(Path(folder) / "downmixed.mp4")
            self.run_ffmpeg(
                "-f", "lavfi", "-i",
                "color=black:size=64x64:rate=25:duration=1,"
                "drawbox=color=white:t=fill:enable='gte(t,0.48)'",
                "-f", "lavfi", "-i",
                "aevalsrc=0|0|0.8*sin(2*PI*440*t)*gte(t\\,0.48)|0|0|0|0|0:"
                "s=48000:d=1:c=7.1",
                "-af", mix, "-c:v", "mpeg4", "-c:a", "aac", output,
            )
            measured = self.run_ffmpeg(
                "-i", output, "-vf", "blackdetect=d=0.2",
                "-af", "silencedetect=n=-30dB:d=0.2", "-f", "null", "-",
            )
        video_onset = float(re.search(r"black_end:([\d.]+)", measured).group(1))
        audio_onset = float(re.search(r"silence_end: ([\d.]+)", measured).group(1))
        self.assertAlmostEqual(video_onset, 0.48, delta=0.001)
        self.assertAlmostEqual(audio_onset, 0.48, delta=0.02)
        self.assertLessEqual(abs(video_onset - audio_onset), 0.04)

    def test_filter_runs_and_lifts_centre_relative_to_default_downmix(self):
        """Measured against FFmpeg's own stereo conversion, inside the graph."""
        default = "aformat=channel_layouts=stereo,volumedetect"
        mix = audio_downmix.downmix_filter(6, "5.1", "dialogue") + ",volumedetect"
        with TemporaryDirectory() as folder:
            levels = {}
            for channel in ("FC", "FL", "BL"):
                path = self.source(folder, f"{channel}.wav",
                                   f"pan=5.1|{channel}=1.0*c0")
                levels[channel] = (self.level(path, mix),
                                   self.level(path, default))
            ours, theirs = levels["FC"]
            self.assertGreater(ours, theirs + 3.0)           # dialogue louder
            self.assertLess(levels["FL"][0], levels["FL"][1])  # fronts quieter
            self.assertLess(levels["BL"][0], levels["BL"][1])  # surrounds quieter
            self.assertGreater(ours, levels["FL"][0])         # centre leads

    def test_lfe_only_and_full_scale_surround_stay_safe(self):
        with TemporaryDirectory() as folder:
            mix = audio_downmix.downmix_filter(6, "5.1", "dialogue")
            lfe = self.source(folder, "lfe.wav", "pan=5.1|LFE=1.0*c0")
            self.assertLess(self.level(lfe, mix + ",volumedetect"), -80.0)
            loud = self.source(
                folder, "all.wav",
                "pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0,volume=1.0")
            self.assertLessEqual(self.level(loud, mix + ",volumedetect"), 0.01)


class StartTranscodeWiringTests(unittest.TestCase):
    def run_start(self, profile: str, layout: str, channels: int):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            media = streamer.MediaInfo(
                path=root / "film.mkv", duration=180.0, pix_fmt="yuv420p",
                width=1280, height=720, audio_tracks=1,
                audio_streams=[streamer.AudioTrack(
                    0, "eac3", channels, "eng", "", layout, True)],
            )
            session = streamer.Session()
            session.used_software_fallback = False
            proc = mock.MagicMock(pid=12345)
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(streamer, "measure_mean_volume", return_value=-30.0) as measure, \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0.0, device="TV", quality="balanced",
                    audio_profile=profile, subs_file=None,
                    burn_subs=False, title="Film",
                )
            return popen.call_args_list[0].args[0], measure

    def test_dialogue_profile_downmixes_first_and_measures_the_same_signal(self):
        args, measure = self.run_start("dialogue", "5.1", 6)
        chain = args[args.index("-af") + 1].split(",")
        self.assertTrue(chain[0].startswith("pan=stereo|FL="))
        self.assertIn("volume=", chain[1])           # trim after the matrix
        self.assertEqual(args[args.index("-ac") + 1], "2")
        self.assertTrue(measure.call_args.kwargs["downmix"].startswith("pan=stereo|"))

    def test_original_profile_and_stereo_keep_the_previous_arguments(self):
        args, _ = self.run_start("original", "5.1", 6)
        self.assertNotIn("-af", args)
        args, measure = self.run_start("dialogue", "stereo", 2)
        self.assertNotIn("pan=", " ".join(args))
        self.assertNotIn("downmix", measure.call_args.kwargs)

    def test_unknown_surround_layout_falls_back_to_plain_downmix(self):
        args, measure = self.run_start("dialogue", "hexagonal", 6)
        self.assertNotIn("pan=", " ".join(args))
        self.assertNotIn("downmix", measure.call_args.kwargs)
        self.assertEqual(args[args.index("-ac") + 1], "2")


if __name__ == "__main__":
    unittest.main()
