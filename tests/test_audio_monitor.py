"""Audio meter memory and incremental pairing regression tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from audio_monitor import AudioMonitor
import audio_monitor
from unittest import mock


class AudioMonitorAudioSelectionTests(unittest.TestCase):
    def test_selected_audio_stream_is_used_for_analysis(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            monitor = AudioMonitor()
            with mock.patch.object(audio_monitor.subprocess, "Popen") as popen, \
                 mock.patch.object(audio_monitor.threading, "Thread"):
                popen.return_value.poll.return_value = 0
                monitor.start(Path(folder) / "movie.mkv", [], offset=33,
                              audio_track_index=1)
                args = popen.call_args.args[0]
                filtergraph = args[args.index("-filter_complex") + 1]
                self.assertIn("[0:a:1]aformat=", filtergraph)
                self.assertIn("-ss", args)
                monitor.stop()


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



class AudioMonitorCoverageTests(unittest.TestCase):
    def test_long_seek_does_not_repeat_last_analysed_window(self):
        monitor = AudioMonitor()
        with monitor._lock:
            monitor._times.extend([0.0, 0.1, 0.2, 0.3])
            for samples in (monitor._in_rms, monitor._out_rms,
                            monitor._in_peak, monitor._out_peak,
                            monitor._in_l, monitor._in_r,
                            monitor._out_l, monitor._out_r):
                samples.extend([-20.0] * 4)
        self.assertIsNotNone(monitor.sample_at(0.32))
        self.assertIsNone(monitor.sample_at(0.4))
        self.assertIsNone(monitor.sample_at(60.0))
        self.assertAlmostEqual(monitor.analyzed_until, 0.3)

    def test_new_decoder_samples_become_available_without_stale_values(self):
        monitor = AudioMonitor()
        with monitor._lock:
            monitor._times.extend([0.0, 0.1])
            for samples in (monitor._in_rms, monitor._out_rms,
                            monitor._in_peak, monitor._out_peak,
                            monitor._in_l, monitor._in_r,
                            monitor._out_l, monitor._out_r):
                samples.extend([-20.0, -15.0])
        self.assertIsNone(monitor.sample_at(20.0))
        with monitor._lock:
            monitor._times.append(20.0)
            for samples in (monitor._in_rms, monitor._out_rms,
                            monitor._in_peak, monitor._out_peak,
                            monitor._in_l, monitor._in_r,
                            monitor._out_l, monitor._out_r):
                samples.append(-10.0)
        self.assertAlmostEqual(monitor.sample_at(20.03).in_rms, -10.0)
        self.assertIsNone(monitor.sample_at(20.51))

    def test_empty_and_before_initial_window_are_unknown(self):
        monitor = AudioMonitor()
        self.assertIsNone(monitor.sample_at(0))
        monitor._offset = 5.0
        with monitor._lock:
            monitor._times.append(5.0)
            for samples in (monitor._in_rms, monitor._out_rms,
                            monitor._in_peak, monitor._out_peak,
                            monitor._in_l, monitor._in_r,
                            monitor._out_l, monitor._out_r):
                samples.append(-30.0)
        self.assertIsNone(monitor.sample_at(4.5))
        self.assertIsNotNone(monitor.sample_at(5.05))
        self.assertIsNone(monitor.sample_at(6.0))


class AudioMonitorReadBoundsTests(unittest.TestCase):
    def test_reader_reads_a_bounded_chunk_per_poll(self):
        from audio_monitor import _Reader

        reader = _Reader(Path("unused"))
        reader._fh = mock.Mock()
        reader._fh.read.return_value = ""
        reader.poll()
        reader._fh.read.assert_called_once_with(audio_monitor._MAX_READ_BYTES)

    def test_unterminated_fragment_is_bounded(self):
        from audio_monitor import _Reader

        reader = _Reader(Path("unused"))

        class Fake:
            sent = False

            def read(self, size):
                if self.sent:
                    return ""
                self.sent = True
                return "x" * (audio_monitor._MAX_PENDING_BYTES + 5000)

        reader._fh = Fake()
        reader.poll()
        self.assertLessEqual(len(reader._pending), audio_monitor._MAX_PENDING_BYTES)

    def test_large_metadata_file_is_consumed_incrementally(self):
        from audio_monitor import _Reader
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as work:
            path = Path(work) / "in.txt"
            lines = []
            for i in range(4000):
                lines.append(f"frame:{i}")
                lines.append("lavfi.astats.Overall.RMS_level=-20.0")
            path.write_text("\n".join(lines) + "\n")

            reader = _Reader(path)
            first = None
            for _ in range(10_000):
                before = len(reader.records)
                reader.poll()
                if first is None and reader.records:
                    first = len(reader.records)
                if len(reader.records) == before:
                    break
            reader.finish()
            # _Reader owns an open file handle; close it before TemporaryDirectory
            # cleanup, which is required on Windows.
            reader._fh.close()
            # The first bounded read cannot consume the whole multi-hour-scale
            # file at once, and repeated polls still recover every record.
            self.assertIsNotNone(first)
            self.assertLess(first, 4000)
            self.assertEqual(len(reader.records), 4000)


if __name__ == "__main__":
    unittest.main()
