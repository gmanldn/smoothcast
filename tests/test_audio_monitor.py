"""Audio meter memory and incremental pairing regression tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audio_monitor import AudioMonitor


class AudioMonitorPairingTests(unittest.TestCase):
    def test_consumes_only_matched_frames_without_retaining_dict_history(self):
        meter = AudioMonitor()
        from audio_monitor import _Reader
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as work:
            meter._rin = _Reader(Path(work) / "in.txt")
            meter._rout = _Reader(Path(work) / "out.txt")
            meter._offset = 100.0
            for start in range(0, 10_000, 200):
                meter._rin.records.extend(
                    {"pts": i * .1, "rms": -24.0} for i in range(start, start + 200)
                )
                meter._rout.records.extend(
                    {"pts": i * .1, "rms": -16.0} for i in range(start, start + 200)
                )
                meter._pair()
                self.assertEqual(meter._rin.records, [])
                self.assertEqual(meter._rout.records, [])
            self.assertEqual(len(meter._times), 10_000)
            sample = meter.sample_at(100.0 + 987.6)
            self.assertIsNotNone(sample)
            self.assertAlmostEqual(sample.in_rms, -24)
            self.assertAlmostEqual(sample.out_rms, -16)

    def test_preserves_unmatched_frames_until_other_branch_catches_up(self):
        meter = AudioMonitor()
        from audio_monitor import _Reader
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as work:
            meter._rin = _Reader(Path(work) / "in.txt")
            meter._rout = _Reader(Path(work) / "out.txt")
            meter._rin.records.extend({"pts": i, "rms": -22} for i in range(3))
            meter._rout.records.append({"pts": 0, "rms": -11})
            meter._pair()
            self.assertEqual(len(meter._times), 1)
            self.assertEqual(len(meter._rin.records), 2)
            self.assertEqual(len(meter._rout.records), 0)
            meter._rout.records.extend({"pts": i, "rms": -11} for i in range(1, 3))
            meter._pair()
            self.assertEqual(len(meter._times), 3)
            self.assertEqual(meter._rin.records, [])
            self.assertEqual(meter._rout.records, [])


if __name__ == "__main__":
    unittest.main()
