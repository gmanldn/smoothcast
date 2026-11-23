"""Seek precision (issue #240): catt takes whole seconds, so round to nearest."""
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import castctl


class SeekRoundingTests(unittest.TestCase):
    def test_rounds_to_nearest_half_up(self):
        for given, want in ((59.9, 60), (59.4, 59), (0.5, 1), (0.49, 0), (90, 90), (3599.5, 3600)):
            self.assertEqual(castctl.seek_seconds(given), want, given)

    def test_negative_and_non_finite_clamp_to_zero(self):
        for bad in (-5, -0.4, float("nan"), float("inf"), float("-inf"), None, "x"):
            self.assertEqual(castctl.seek_seconds(bad), 0, bad)

    def test_seek_sends_the_rounded_integer(self):
        with mock.patch.object(castctl, "command", return_value=(True, "")) as cmd:
            castctl.seek("TV", 59.9)
        cmd.assert_called_once_with("TV", "seek", "60")

    def test_idempotent_seek_retries_one_timeout_with_same_absolute_target(self):
        with mock.patch.object(
            castctl, "command",
            side_effect=[(False, castctl.COMMAND_TIMEOUT_MESSAGE), (True, "done")],
        ) as cmd:
            self.assertEqual(castctl.seek("TV", 59.9), (True, "done"))
        self.assertEqual(cmd.call_args_list, [
            mock.call("TV", "seek", "60"), mock.call("TV", "seek", "60"),
        ])

    def test_idempotent_commands_do_not_retry_receiver_errors_or_toggles(self):
        for operation, args in (("pause", ()), ("play_toggle", ())):
            with self.subTest(operation=operation), mock.patch.object(
                castctl, "command", return_value=(False, "device busy"),
            ) as cmd:
                self.assertEqual(
                    castctl.idempotent_command("TV", operation, *args),
                    (False, "device busy"),
                )
                cmd.assert_called_once_with("TV", operation)

    def test_idempotent_command_retries_no_more_than_once(self):
        with mock.patch.object(
            castctl, "command", return_value=(False, castctl.COMMAND_TIMEOUT_MESSAGE),
        ) as cmd:
            self.assertEqual(
                castctl.stop("TV"), (False, castctl.COMMAND_TIMEOUT_MESSAGE),
            )
        self.assertEqual(cmd.call_count, 2)

    def test_catt_failure_does_not_return_process_details(self):
        private_text = "Could not load /private/media/film.mkv"
        result = CompletedProcess([], 1, stdout="", stderr=private_text)
        with mock.patch.object(castctl, "log_backend_failure") as log:
            with mock.patch.object(castctl, "_run", return_value=result):
                ok, message = castctl._catt_command("TV", "play")
                self.assertFalse(ok)
                self.assertNotIn(private_text, message)
                self.assertIn("receiver connection", message)
            with mock.patch.object(castctl, "_run", side_effect=OSError(private_text)):
                ok, message = castctl._catt_command("TV", "play")
                self.assertFalse(ok)
                self.assertNotIn(private_text, message)
                self.assertIn("installation", message)
            self.assertEqual(log.call_count, 2)


if __name__ == "__main__":
    unittest.main()
