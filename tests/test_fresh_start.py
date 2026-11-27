"""Fresh start: hung primaries are replaced safely; healthy ones are untouched."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))

import fresh_start  # noqa: E402
import launch  # noqa: E402


class FakeProc:
    def __init__(self, pid, *, ignore_term=False, created=1.0, argv=("python3", "cast_control.py")):
        self.pid, self.ignore_term, self.created, self.argv = pid, ignore_term, created, argv
        self.alive, self.signals = True, []

    def create_time(self): return self.created
    def cmdline(self): return list(self.argv)
    def is_running(self): return self.alive

    def terminate(self):
        self.signals.append("TERM")
        self.alive = self.ignore_term

    def kill(self):
        self.signals.append("KILL")
        self.alive = False


class StopProcessTests(unittest.TestCase):
    def run_stop(self, procs, pids):
        ticks = iter(range(0, 1000))
        return fresh_start.stop_processes(
            pids, grace=1.0, process_factory=lambda pid: procs[pid],
            clock=lambda: next(ticks) * 0.5, sleep=lambda _s: None)

    def test_terminates_politely_then_kills_stubborn_process(self):
        procs = {10: FakeProc(10), 11: FakeProc(11, ignore_term=True)}
        gone = self.run_stop(procs, [10, 11])
        self.assertEqual(sorted(gone), [10, 11])
        self.assertEqual(procs[10].signals, ["TERM"])
        self.assertEqual(procs[11].signals, ["TERM", "KILL"])

    def test_refuses_own_and_init_pids(self):
        import os
        procs = {1: FakeProc(1), os.getpid(): FakeProc(os.getpid())}
        self.assertEqual(self.run_stop(procs, [1, os.getpid()]), [])
        self.assertTrue(all(not p.signals for p in procs.values()))

    def test_missing_process_is_skipped(self):
        def factory(pid):
            raise ProcessLookupError(pid)
        self.assertEqual(fresh_start.stop_processes([77], process_factory=factory), [])

    def test_changed_identity_before_signal_is_not_signalled(self):
        proc = FakeProc(20)
        original = proc.create_time
        calls = {"n": 0}

        def shifting():
            calls["n"] += 1
            return original() if calls["n"] == 1 else 99.0  # PID reused
        proc.create_time = shifting
        self.run_stop({20: proc}, [20])
        self.assertEqual(proc.signals, [])


class FlagTests(unittest.TestCase):
    def test_take_flag(self):
        self.assertEqual(fresh_start.take_flag(["--fresh", "a.mp4"]), (True, ["a.mp4"]))
        self.assertEqual(fresh_start.take_flag(["a.mp4"]), (False, ["a.mp4"]))


class ReclaimTests(unittest.TestCase):
    def test_hung_primary_is_reclaimed_but_probe_unavailable_is_not(self):
        with mock.patch.object(launch, "gui_instances", return_value=[5]), \
                mock.patch.object(launch, "managed_target", return_value=None):
            seen = []
            with mock.patch.object(launch, "activate_existing", return_value=False):
                self.assertIsNone(launch.ensure_single_instance(
                    [], reclaim=lambda pids: seen.append(pids) or True))
            self.assertEqual(seen, [[5]])
            with mock.patch.object(launch, "activate_existing", return_value=None):
                self.assertEqual(launch.ensure_single_instance(
                    [], reclaim=lambda pids: True), 3)
            with mock.patch.object(launch, "activate_existing", return_value=False):
                self.assertEqual(launch.ensure_single_instance([]), 3)
            with mock.patch.object(launch, "activate_existing", return_value=False):
                self.assertEqual(launch.ensure_single_instance(
                    [], reclaim=lambda pids: False), 3)


if __name__ == "__main__":
    unittest.main()
