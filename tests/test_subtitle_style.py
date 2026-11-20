"""SC-025: preset subtitle styling that never overrides authored ASS styling."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ast
import config_control
import streamer
import subtitle_style


class PresetPolicyTests(unittest.TestCase):
    def test_default_and_bad_values_change_nothing(self):
        for value in (None, "", "Large", "large ", 3, ["large"], "x'; drop", True):
            self.assertEqual(subtitle_style.normalize(value), "default")
        self.assertIsNone(subtitle_style.force_style("default", codec="subrip"))
        self.assertIsNone(subtitle_style.force_style(object(), codec="subrip"))

    def test_presets_apply_only_to_plain_text(self):
        for preset in ("large", "high-contrast", "raised"):
            for codec in ("subrip", "SRT", "webvtt", "mov_text", "text"):
                self.assertTrue(
                    subtitle_style.force_style(preset, codec=codec).startswith(
                        ":force_style='"), (preset, codec))
            for codec in ("ass", "ssa", "dvd_subtitle", "hdmv_pgs_subtitle", "weird"):
                self.assertIsNone(subtitle_style.force_style(preset, codec=codec))
            self.assertTrue(subtitle_style.force_style(preset, path="/a/b/Film.SRT"))
            self.assertTrue(subtitle_style.force_style(preset, path="x.vtt"))
            for path in ("x.ass", "x.ssa", "x", None, ""):
                self.assertIsNone(subtitle_style.force_style(preset, path=path))
            self.assertIsNone(subtitle_style.force_style(preset))
        # A known codec wins over a misleading file name.
        self.assertIsNone(subtitle_style.force_style("large", codec="ass", path="x.srt"))

    def test_output_is_a_closed_safe_alphabet(self):
        for preset in subtitle_style.PRESETS:
            option = subtitle_style.force_style(preset, codec="subrip")
            if option is None:
                self.assertEqual(preset, "default")
                continue
            body = option[len(":force_style='"):-1]
            self.assertTrue(option.endswith("'"))
            self.assertNotIn("'", body)
            self.assertNotIn(":", body)
            self.assertRegex(body, r"^[A-Za-z]+=[&H0-9A-Fa-f.]+(,[A-Za-z]+=[&H0-9A-Fa-f.]+)*$")

    def test_config_is_validated_and_defaulted(self):
        # cast_widgets imports GTK, so read its DEFAULTS literal from source.
        source = (Path(__file__).resolve().parents[1] / "src/cast_widgets.py").read_text()
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "DEFAULTS")
        defaults = ast.literal_eval(
            ast.get_source_segment(source, node.value).replace("castctl.DEFAULT_DEVICE", "'TV'"))
        self.assertEqual(defaults["subtitle_style"], "default")
        for good in subtitle_style.PRESETS:
            cfg = config_control.sanitise_config({"subtitle_style": good}, defaults)
            self.assertEqual(cfg["subtitle_style"], good)
        for bad in ("evil", "", None, 7, ["large"], {"a": 1}, "Large"):
            cfg = config_control.sanitise_config({"subtitle_style": bad}, defaults)
            self.assertEqual(cfg["subtitle_style"], "default", bad)
        self.assertEqual(subtitle_style.from_config({"subtitle_style": "large"}), "large")
        self.assertEqual(subtitle_style.from_config({"subtitle_style": "evil"}), "default")
        self.assertEqual(subtitle_style.from_config(None), "default")


class CastSessionWiringTests(unittest.TestCase):
    """cast_session imports GTK, so check its source like other GUI modules."""

    def test_a_preset_forces_burn_in_and_reaches_every_transcode_start(self):
        source = (Path(__file__).resolve().parents[1] / "src/cast_session.py").read_text()
        # A receiver-side sidecar cannot be restyled, so a preset burns in.
        self.assertIn("or delay != 0 or preset != subtitle_style.DEFAULT", source)
        self.assertIn("subtitle_preset=preset", source)                       # first cast
        self.assertIn("subtitle_preset=subtitle_style.from_config(self.cfg)", source)  # restart
        self.assertEqual(source.count("start_transcode("), source.count("subtitle_preset="))


class FilterGraphTests(unittest.TestCase):
    def graph(self, **kwargs) -> str:
        args = streamer.Session()._filter_args(
            True, kwargs.pop("staged", Path("burned_subs.srt")), True, 1.0, **kwargs)
        return args[args.index("-vf") + 1] if "-vf" in args else ""

    def test_default_graph_is_byte_identical(self):
        self.assertEqual(self.graph(), "subtitles=filename=burned_subs.srt")
        self.assertEqual(self.graph(subtitle_force_style=""), self.graph())

    def test_style_is_appended_to_the_subtitles_filter(self):
        option = subtitle_style.force_style("large", codec="subrip")
        self.assertEqual(
            self.graph(subtitle_force_style=option),
            "subtitles=filename=burned_subs.srt" + option)
        embedded = self.graph(
            staged=None, embedded_subtitle_index=2,
            embedded_source=Path("/m/film.mkv"), subtitle_force_style=option)
        self.assertIn(":si=2" + option, embedded)

    def test_style_survives_delay_shift_wrapping(self):
        option = subtitle_style.force_style("raised", codec="subrip")
        graph = self.graph(subtitle_force_style=option, subtitle_delay_ms=500)
        parts = graph.split(",setpts")
        self.assertIn(option, graph)
        self.assertTrue(graph.startswith("setpts="))
        self.assertEqual(len(parts), 2)


class StartTranscodeTests(unittest.TestCase):
    def run_start(self, preset, *, subs_name=None, embedded=None):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            subs = None
            if subs_name:
                subs = root / subs_name
                subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n"
                                if subs_name.endswith(".srt") else
                                "[Script Info]\nScriptType: v4.00+\n")
            media = streamer.MediaInfo(
                path=root / "film.mkv", duration=60.0, pix_fmt="yuv420p",
                width=1280, height=720,
                subtitle_tracks=[streamer.SubtitleTrack(2, "subrip", "eng")],
            )
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
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0.0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=subs,
                    burn_subs=bool(subs), title="Film",
                    embedded_subtitle_index=embedded, subtitle_preset=preset,
                )
            args = popen.call_args_list[0].args[0]
            return args[args.index("-vf") + 1] if "-vf" in args else ""

    def test_srt_gets_the_preset_and_ass_keeps_its_own_style(self):
        self.assertIn("force_style='FontSize=22", self.run_start("large", subs_name="a.srt"))
        self.assertNotIn("force_style", self.run_start("large", subs_name="a.ass"))
        self.assertNotIn("force_style", self.run_start("default", subs_name="a.srt"))
        self.assertNotIn("force_style", self.run_start("bogus", subs_name="a.srt"))

    def test_embedded_text_track_gets_the_preset(self):
        self.assertIn("si=2:force_style='FontSize=22", self.run_start("large", embedded=2))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class RealRenderTests(unittest.TestCase):
    """libass must accept the generated option and visibly apply it."""

    def render(self, folder: Path, option: str):
        srt = folder / "a.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello World dialogue\n")
        out = folder / ("o%d.pgm" % len(list(folder.glob("o*.pgm"))))
        probe = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                               capture_output=True, text=True).stdout
        if " subtitles " not in probe:
            self.skipTest("FFmpeg lacks the libass subtitles filter")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=2",
             "-vf", f"subtitles=filename=a.srt{option}", "-frames:v", "1",
             "-pix_fmt", "gray", str(out)],
            cwd=folder, check=True, timeout=60)
        data = out.read_bytes()[-640 * 360:]
        rows = [y for y in range(360) if any(b > 230 for b in data[y * 640:(y + 1) * 640])]
        bright = sum(1 for b in data if b > 230)
        return bright, (min(rows), max(rows)) if rows else None

    def test_large_is_bigger_and_raised_is_higher(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            base_px, base_rows = self.render(root, "")
            large_px, _ = self.render(root, subtitle_style.force_style("large", codec="subrip"))
            _, raised_rows = self.render(root, subtitle_style.force_style("raised", codec="subrip"))
            self.assertGreater(large_px, base_px * 1.5)
            self.assertLess(raised_rows[1], base_rows[1] - 15)


if __name__ == "__main__":
    unittest.main()
