"""Canary tests for the allowlisted public error-tail projection (#620).

The public projection must never leak arbitrary log text: every assertion feeds
hostile or sensitive input and checks that only approved static data survives.
GTK-free, no network; the publish transport is always a fake.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import error_tail  # noqa: E402

CANARIES = (
    "user@example.com",
    "http://10.0.0.9:8767/private",
    "magnet:?xt=urn:btih:deadbeefcafefeed",
    "fe80::1",
    "00:11:22:33:44:55",
    "alice-laptop.local",
    "/home/alice/Movies/Private Film.mkv",
    r"C:\Users\alice\Secret.mkv",
    "token=sk-live-SECRET",
    "password: hunter2",
    "<script>alert(1)</script>",
)


class SanitizeCanaryTests(unittest.TestCase):
    def _hostile_record(self) -> str:
        body = " ".join(CANARIES)
        return (
            "2026-11-26T04:00:00  boom cast.command_failed \n"
            '  File "/home/alice/src/cast_ui.py", line 42, in send\n'
            f"    detail {body}\n"
        )

    def test_public_output_carries_no_sensitive_or_arbitrary_text(self):
        out = error_tail.sanitize_records(
            [self._hostile_record()], known=frozenset({"cast_ui.py"})
        )
        for canary in CANARIES:
            self.assertNotIn(canary, out)
        self.assertNotIn("boom", out)
        self.assertNotIn("detail", out)
        # Approved static catalogue data does survive.
        self.assertIn("cast.command_failed", out)
        self.assertIn("The receiver command failed.", out)
        self.assertIn("at cast_ui.py", out)
        self.assertNotIn(":42 send", out)

    def test_known_module_does_not_authorise_arbitrary_frame_fields(self):
        record = ('2026-11-26T04:00:00 cast.command_failed\n'
                  '  File "/home/alice/src/cast_ui.py", line 987654321, in secret_token_ABC')
        out = error_tail.sanitize_records([record], known=frozenset({"cast_ui.py"}))
        self.assertIn("at cast_ui.py", out)
        self.assertNotIn("987654321", out)
        self.assertNotIn("secret_token_ABC", out)

    def test_records_without_a_known_code_are_omitted(self):
        out = error_tail.sanitize_records(
            ["2026-11-26T04:00:00  totally unknown failure with /etc/passwd"],
            known=frozenset(),
        )
        self.assertEqual(out, "")

    def test_unknown_and_non_python_frames_are_dropped(self):
        record = (
            "2026-11-26T04:00:00 cast.command_failed\n"
            '  File "/home/alice/evil.py", line 1, in run\n'
            '  File "C:/x/notpython.py", line 9, in y\n'
        )
        out = error_tail.sanitize_records([record], known=frozenset({"cast_ui.py"}))
        self.assertNotIn("evil.py", out)
        self.assertNotIn("notpython.py", out)
        self.assertIn("cast.command_failed", out)


class BoundsTests(unittest.TestCase):
    def test_cap_is_never_exceeded_and_newest_records_survive(self):
        records = [
            f"2026-11-26T04:{n // 60:02d}:{n % 60:02d} cast.receiver_offline" for n in range(200)
        ]
        out = error_tail.sanitize_records(records, known=frozenset(), max_chars=500)
        self.assertLessEqual(len(out), 500)
        self.assertIn("04:03:19", out)  # newest kept
        self.assertNotIn("04:00:00", out)  # oldest dropped whole

    def test_record_larger_than_cap_is_dropped_not_cut(self):
        out = error_tail.sanitize_records(
            ["2026-11-26T04:00:00 cast.receiver_offline"], known=frozenset(), max_chars=10
        )
        self.assertEqual(out, "")

    def test_requested_cap_cannot_exceed_hard_limit(self):
        records = ["2026-11-26T04:00:00 cast.receiver_offline"] * 100
        self.assertLessEqual(len(error_tail.sanitize_records(
            records, known=frozenset(), max_chars=100_000)), 2000)
        self.assertEqual(error_tail.sanitize_records(records, max_chars=-1), "")

    def test_default_cap_is_two_thousand(self):
        self.assertEqual(error_tail.MAX_TAIL_CHARS, 2000)


class ReadRecordsTests(unittest.TestCase):
    def test_missing_and_empty_logs_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nope.log"
            empty = Path(directory) / "empty.log"
            empty.write_text("", encoding="utf-8")
            self.assertEqual(error_tail.read_records(missing), [])
            self.assertEqual(error_tail.read_records(empty), [])

    def test_partial_first_record_is_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_text(
                "garbage continuation of an old record\n"
                "2026-11-26T04:00:00 cast.command_failed\n",
                encoding="utf-8",
            )
            records = error_tail.read_records(log)
            self.assertEqual(len(records), 1)
            self.assertIn("cast.command_failed", records[0])

    def test_read_limit_cannot_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_bytes(b"2026-11-26T04:00:00 cast.command_failed\n"
                            + b"x" * error_tail.MAX_READ_BYTES
                            + b"\n2026-11-26T05:00:00 cast.receiver_offline\n")
            records = error_tail.read_records(log, max_bytes=10**9)
            self.assertEqual(len(records), 1)
            self.assertIn("cast.receiver_offline", records[0])
            self.assertEqual(error_tail.read_records(log, max_bytes=-1), [])

    def test_invalid_utf8_is_replaced_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_bytes(b"2026-11-26T04:00:00 cast.command_failed \xff\xfe\n")
            records = error_tail.read_records(log)
            self.assertTrue(records)

    def test_traceback_continuation_stays_in_one_record(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_text(
                "2026-11-26T04:00:00 cast.command_failed\n"
                "Traceback (most recent call last):\n"
                "  boom\n",
                encoding="utf-8",
            )
            records = error_tail.read_records(log)
            self.assertEqual(len(records), 1)
            self.assertIn("Traceback", records[0])


class PublishTests(unittest.TestCase):
    def _snapshot(self) -> dict:
        return {"tail": "code", "observed_at": 1, "build_sha": "a" * 40,
                "platform_family": "Linux"}

    def test_disabled_by_default_reports_configuration(self):
        with self.assertRaises(error_tail.PublishDisabled):
            error_tail.resolve_target({})

    def test_rejects_protected_branch_and_bad_repo(self):
        with self.assertRaises(error_tail.PublishDisabled):
            error_tail.resolve_target({"SMOOTHCAST_ERRTAIL_REPO": "o/r",
                                       "SMOOTHCAST_ERRTAIL_BRANCH": "develop"})
        with self.assertRaises(error_tail.PublishDisabled):
            error_tail.resolve_target({"SMOOTHCAST_ERRTAIL_REPO": "not-a-repo"})

    def test_publish_calls_transport_and_skips_unchanged(self):
        calls = []
        target = error_tail.resolve_target(
            {"SMOOTHCAST_ERRTAIL_REPO": "owner/diag", "SMOOTHCAST_ERRTAIL_BRANCH": "snap"},
            transport=lambda repo, branch, path, content: calls.append((repo, branch, content)),
        )
        snapshot = self._snapshot()
        body = error_tail.render_envelope(snapshot)
        self.assertEqual(error_tail.publish(snapshot, target), "published")
        self.assertEqual(error_tail.publish(
            snapshot, target, fetch_current=lambda t: body), "unchanged")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "owner/diag")

    def test_new_observation_time_does_not_republish_identical_tail(self):
        calls = []
        target = error_tail.resolve_target({"SMOOTHCAST_ERRTAIL_REPO": "owner/diag"},
                                           transport=lambda *args: calls.append(args))
        old = self._snapshot()
        new = dict(old, observed_at=2)
        fetch = lambda target: error_tail.render_envelope(old)
        self.assertEqual(error_tail.publish(new, target, fetch_current=fetch), "unchanged")
        self.assertFalse(calls)
        for change in (dict(new, tail="different"), dict(new, build_sha="b" * 40),
                       dict(new, platform_family="Windows")):
            self.assertEqual(error_tail.publish(change, target, fetch_current=fetch), "published")
        self.assertEqual(len(calls), 3)

    def test_destination_rejects_ref_aliases_and_query_injection(self):
        for branch in ("refs/heads/main", "MAIN", "HEAD", "snap?ref=main", "snap//x", "snap.lock"):
            with self.subTest(branch=branch), self.assertRaises(error_tail.PublishDisabled):
                error_tail.resolve_target({"SMOOTHCAST_ERRTAIL_REPO": "owner/diag",
                                           "SMOOTHCAST_ERRTAIL_BRANCH": branch})
        for path in ("latest/x?ref=main", "latest/../x", "latest//x", "/latest/x"):
            with self.subTest(path=path), self.assertRaises(error_tail.PublishDisabled):
                error_tail.resolve_target({"SMOOTHCAST_ERRTAIL_REPO": "owner/diag",
                                           "SMOOTHCAST_ERRTAIL_PATH": path})

    def test_transport_failure_propagates(self):
        def boom(repo, branch, path, content):
            raise error_tail.PublishDisabled("auth failed")

        target = error_tail.resolve_target(
            {"SMOOTHCAST_ERRTAIL_REPO": "owner/diag"}, transport=boom
        )
        with self.assertRaises(error_tail.PublishDisabled):
            error_tail.publish(self._snapshot(), target)

    def test_envelope_is_deterministic_json_without_raw_objects(self):
        text = error_tail.render_envelope(self._snapshot())
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["build_sha"], "a" * 40)


class MainTests(unittest.TestCase):
    def test_preview_is_offline_and_emits_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_text("2026-11-26T04:00:00 cast.command_failed\n", encoding="utf-8")
            import io
            from contextlib import redirect_stdout

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = error_tail.main(["--preview", "--log", str(log)])
            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("cast.command_failed", payload["tail"])

    def test_publish_without_configuration_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            log.write_text("2026-11-26T04:00:00 cast.command_failed\n", encoding="utf-8")
            code = error_tail.main(["--publish", "--log", str(log)], env={})
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
