"""Natural, episode-aware ordering of queued files (issue #271)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import playlist_control as pc


class NaturalOrderTests(unittest.TestCase):
    def test_numbers_compare_numerically(self):
        names = ["/m/ep10.mkv", "/m/ep2.mkv", "/m/ep1.mkv"]
        self.assertEqual(pc.natural_order(names), ["/m/ep1.mkv", "/m/ep2.mkv", "/m/ep10.mkv"])

    def test_case_is_ignored_and_order_is_deterministic(self):
        names = ["/m/B.mkv", "/m/a.mkv", "/m/A.mkv"]
        self.assertEqual(pc.natural_order(names), pc.natural_order(list(reversed(names))))
        self.assertEqual(pc.natural_order(names)[-1], "/m/B.mkv")

    def test_episode_markers_are_detected(self):
        cases = {
            "Show.S01E02.1080p.mkv": (1, 2), "show s2e10.mp4": (2, 10),
            "Show S03.E04.mkv": (3, 4), "Show.1x05.avi": (1, 5),
            "Show.S01E02E03.mkv": (1, 2),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(pc.episode_of(name), expected)

    def test_false_positives_are_not_episodes(self):
        for name in ("movie.mkv", "mix02.mkv", "clip.1080x1920.mkv", "S01E.mkv", "ex1.mkv"):
            with self.subTest(name=name):
                self.assertIsNone(pc.episode_of(name))

    def test_seasons_and_episodes_sort_by_number_not_text(self):
        names = [
            "/tv/Show.S02E01.mkv", "/tv/Show.S01E10.mkv", "/tv/Show.S01E2.mkv",
            "/tv/Show.S01E01.mkv", "/tv/extras.mkv",
        ]
        self.assertEqual(pc.natural_order(names), [
            "/tv/Show.S01E01.mkv", "/tv/Show.S01E2.mkv", "/tv/Show.S01E10.mkv",
            "/tv/Show.S02E01.mkv", "/tv/extras.mkv",
        ])

    def test_episode_order_beats_title_text_within_a_folder(self):
        names = ["/tv/Zed.S01E01.mkv", "/tv/Alpha.S01E02.mkv"]
        self.assertEqual(pc.natural_order(names), names)

    def test_folders_sort_naturally_and_inputs_are_not_mutated(self):
        names = ["/tv/Season 10/a.mkv", "/tv/Season 2/a.mkv"]
        snapshot = list(names)
        self.assertEqual(pc.natural_order(names), ["/tv/Season 2/a.mkv", "/tv/Season 10/a.mkv"])
        self.assertEqual(names, snapshot)

    def test_empty_and_single_inputs(self):
        self.assertEqual(pc.natural_order([]), [])
        self.assertEqual(pc.natural_order(["/a.mkv"]), ["/a.mkv"])

    def test_queue_uses_it_for_batches_but_playlists_keep_authored_order(self):
        source = (ROOT / "src/cast_queue.py").read_text("utf-8")
        self.assertEqual(source.count("playlist_control.natural_order("), 2)
        loader = source.split("def _playlist_open_chosen", 1)[1][:1500]
        self.assertNotIn("natural_order", loader)


if __name__ == "__main__":
    unittest.main()
