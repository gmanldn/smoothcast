"""Optional EBU R128 loudness normalisation (no GTK, FFmpeg or network)."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import loudness
import streamer


class LoudnessChoiceTests(unittest.TestCase):
    def test_off_is_the_default_and_produces_no_filter(self):
        self.assertEqual(loudness.normalize("off"), "off")
        self.assertEqual(loudness.filter_args("off"), [])
        self.assertEqual(loudness.filter_args("nonsense"), [])
        self.assertEqual(loudness.filter_args(None), [])
        self.assertEqual(loudness.target_lufs("off"), 0.0)

    def test_programme_and_album_targets_are_measured_and_peak_limited(self):
        programme = loudness.filter_args("programme")
        album = loudness.filter_args("album")
        self.assertEqual(programme, ["loudnorm=I=-16:TP=-1.5:LRA=11"])
        self.assertEqual(album, ["loudnorm=I=-18:TP=-1.5:LRA=11"])

    def test_choices_are_stable_for_the_ui(self):
        self.assertEqual(loudness.choices(), [
            ("Off", "off"),
            ("Programme (-16 LUFS)", "programme"),
            ("Album (-18 LUFS)", "album"),
        ])
        self.assertEqual(loudness.label("album"), "Album (-18 LUFS)")


class StreamerChainTests(unittest.TestCase):
    def test_audio_filters_appends_loudness_after_the_limiter(self):
        chain = streamer.audio_filters("dialogue", 6.0, "programme")
        self.assertEqual(chain[0], "volume=6dB")
        self.assertIn("alimiter=limit=0.95:attack=5:release=80", chain)
        self.assertEqual(chain[-1], "loudnorm=I=-16:TP=-1.5:LRA=11")

    def test_original_profile_can_still_be_normalised(self):
        self.assertEqual(streamer.audio_filters("original"), [])
        self.assertEqual(streamer.audio_filters("original", 0.0, "album"),
                         ["loudnorm=I=-18:TP=-1.5:LRA=11"])

    def test_effective_chain_keeps_auto_trim_for_dialogue(self):
        with mock.patch.object(streamer, "auto_trim_gain", return_value=2.0):
            chain = streamer.effective_chain("film.mkv", "dialogue", 1.0, loudness_mode="programme")
        self.assertEqual(chain[0], "volume=3dB")
        self.assertEqual(chain[-1], "loudnorm=I=-16:TP=-1.5:LRA=11")

    def test_effective_chain_skips_measurement_for_original_unless_enabled(self):
        with mock.patch.object(streamer, "auto_trim_gain") as trim:
            self.assertEqual(streamer.effective_chain("film.mkv", "original"), [])
            trim.assert_not_called()
            self.assertEqual(
                streamer.effective_chain("film.mkv", "original", loudness_mode="album"),
                ["loudnorm=I=-18:TP=-1.5:LRA=11"],
            )
            trim.assert_not_called()


if __name__ == "__main__":
    unittest.main()