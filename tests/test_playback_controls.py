"""Loop, queue progression and persisted sleep-timer decision tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playback_state import next_media, shuffle_order, sleep_deadline, timer_expired


class PlaybackControlsTests(unittest.TestCase):
    def test_loop_replays_current_even_with_autonext(self):
        queue = ["/videos/one.mp4", "/videos/two.mp4"]
        self.assertEqual(
            next_media(queue[0], queue, repeat_current=True, auto_next=True),
            queue[0],
        )

    def test_autonext_advances_only_when_requested(self):
        queue = ["/videos/one.mp4", "/videos/two.mp4"]
        self.assertEqual(
            next_media(queue[0], queue, repeat_current=False, auto_next=True),
            queue[1],
        )
        self.assertIsNone(next_media(queue[1], queue, repeat_current=False, auto_next=True))
        self.assertIsNone(next_media(queue[0], queue, repeat_current=False, auto_next=False))
        self.assertIsNone(next_media("/missing", queue, repeat_current=False, auto_next=True))

    def test_loop_all_wraps_last_to_first(self):
        queue = ["/videos/one.mp4", "/videos/two.mp4", "/videos/three.mp4"]
        self.assertEqual(
            next_media(queue[2], queue, repeat_current=False, auto_next=True,
                       repeat_all=True),
            queue[0],
        )
        # Without loop-all the last entry ends the queue.
        self.assertIsNone(
            next_media(queue[2], queue, repeat_current=False, auto_next=True)
        )
        # Repeat-one still wins over loop-all.
        self.assertEqual(
            next_media(queue[1], queue, repeat_current=True, auto_next=True,
                       repeat_all=True),
            queue[1],
        )

    def test_shuffled_order_drives_auto_advance(self):
        queue = ["/a", "/b", "/c"]
        order = ["/c", "/a", "/b"]
        self.assertEqual(
            next_media("/c", queue, repeat_current=False, auto_next=True, order=order),
            "/a",
        )
        self.assertEqual(
            next_media("/b", queue, repeat_current=False, auto_next=True,
                       repeat_all=True, order=order),
            "/c",
        )

    def test_shuffle_order_is_deterministic_and_a_permutation(self):
        queue = ["/a", "/b", "/c", "/d"]
        first = shuffle_order(queue, 7)
        self.assertEqual(first, shuffle_order(queue, 7))
        self.assertCountEqual(first, queue)
        self.assertEqual(queue, ["/a", "/b", "/c", "/d"])  # input untouched

    def test_sleep_deadline_is_wall_clock_and_can_be_disabled(self):
        self.assertEqual(sleep_deadline(1000.0, 15), 1900.0)
        self.assertEqual(sleep_deadline(1000.0, 0), 0.0)
        self.assertFalse(timer_expired(1900.0, 1899.99))
        self.assertTrue(timer_expired(1900.0, 1900.0))
        self.assertFalse(timer_expired(0, 3000))

    def test_corrupt_deadline_does_not_stop_cast(self):
        for value in ("bad", None, -5.0, "nan", "inf"):
            with self.subTest(value=value):
                self.assertFalse(timer_expired(value, 99999999.0))


if __name__ == "__main__":
    unittest.main()
