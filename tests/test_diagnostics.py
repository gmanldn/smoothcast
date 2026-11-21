"""GTK-free tests for bounded, redacted diagnostic bundle export."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import diagnostics
import reliability_metrics
import version


class RedactionTests(unittest.TestCase):
    def test_masks_ipv4_addresses(self):
        text = diagnostics.redact("cast to 192.168.1.50 on http://10.0.0.9:8767/x")
        self.assertNotIn("192.168.1.50", text)
        self.assertNotIn("10.0.0.9", text)
        self.assertIn("[ip]", text)

    def test_collapses_absolute_paths_to_basenames(self):
        self.assertEqual(
            diagnostics.redact("/home/alice/Movies/My Film.mkv", home="/home/alice"),
            "My Film.mkv",
        )
        self.assertEqual(
            diagnostics.redact(r"C:\Users\alice\Movies\Film.mkv"),
            "Film.mkv",
        )

    def test_removes_home_directory(self):
        text = diagnostics.redact("log at /home/alice/.config/x.log", home="/home/alice")
        self.assertNotIn("/home/alice", text)

    def test_leaves_plain_prose_untouched(self):
        self.assertEqual(diagnostics.redact("HLS buffer starved"), "HLS buffer starved")

    def test_bounds_long_values(self):
        text = diagnostics.redact("x" * (diagnostics.MAX_STRING + 200))
        self.assertLessEqual(len(text), diagnostics.MAX_STRING + 1)

    def test_redact_config_masks_credentials_and_paths(self):
        result = diagnostics.redact_config(
            {"api_token": "abc", "resume": {"a.mkv": "/home/bob/Movies/a.mkv"}},
            home="/home/bob",
        )
        self.assertEqual(result["api_token"], "[redacted]")
        self.assertEqual(result["resume"]["a.mkv"], "a.mkv")


class CollectTests(unittest.TestCase):
    def test_tails_and_redacts_the_error_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "errors.log"
            lines = [f"error {n} at /home/alice/Movies/film-{n}.mkv 10.0.0.{n}" for n in range(500)]
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with mock.patch.object(diagnostics, "tool_version", return_value=""):
                payload = diagnostics.collect(error_log=log, home="/home/alice")
        self.assertEqual(len(payload["errors"]), diagnostics.MAX_ERROR_LINES)
        blob = json.dumps(payload)
        self.assertNotIn("/home/alice", blob)
        self.assertNotIn("10.0.0.", blob)
        self.assertIn("[ip]", blob)  # addresses were masked, not left raw

    def test_reports_missing_error_log_without_failing(self):
        with mock.patch.object(diagnostics, "tool_version", return_value=""):
            payload = diagnostics.collect(error_log=Path("/does/not/exist/errors.log"))
        self.assertEqual(payload["errors"], [])

    def test_includes_version_and_tools(self):
        payload = diagnostics.collect()
        self.assertEqual(payload["smoothcast"]["label"], version.label())
        self.assertIn("ffmpeg", payload["tools"])

    def test_includes_only_recent_allowlisted_reliability_summaries(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reliability.json"
            session = reliability_metrics.SessionMetrics(
                "cast", wall_time=time.time(),
            )
            summary = session.finish("completed")
            summary["title"] = "Private Film Name"
            reliability_metrics.append(summary, path)
            with mock.patch.object(diagnostics, "tool_version", return_value=""):
                payload = diagnostics.collect(reliability=path)
        self.assertEqual(len(payload["reliability"]), 1)
        self.assertNotIn("title", payload["reliability"][0])
        self.assertNotIn("Private Film Name", json.dumps(payload))


class WriteBundleTests(unittest.TestCase):
    def test_writes_owner_only_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "diagnostics.json"
            path = diagnostics.write_bundle(destination, {"a": 1})
            self.assertEqual(path, destination)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"a": 1})
            if os.name != "nt":
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_refuses_oversized_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "diagnostics.json"
            with self.assertRaises(diagnostics.DiagnosticError):
                diagnostics.write_bundle(destination, {"blob": "x" * 1000}, max_bytes=128)
            self.assertFalse(destination.exists())

    def test_export_produces_a_bounded_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out.json"
            with mock.patch.object(diagnostics, "tool_version", return_value=""):
                path = diagnostics.export(destination=destination, error_log=destination)
            self.assertTrue(path.is_file())
            self.assertLessEqual(path.stat().st_size, diagnostics.MAX_BUNDLE_BYTES)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("platform", payload)


if __name__ == "__main__":
    unittest.main()
