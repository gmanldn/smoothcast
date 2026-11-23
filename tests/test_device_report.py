"""Structured device compatibility reports (issue #275)."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import diagnostics


class ReceiverReportTests(unittest.TestCase):
    def test_dlna_and_cast_receivers_yield_protocol_and_model_only(self):
        dlna = SimpleNamespace(model="BRAVIA X", host="192.168.1.50", name="Living room", key="uuid")
        cast = SimpleNamespace(model="Chromecast HD", manufacturer="Google Inc.",
                               host="192.168.1.60", name="Kitchen", uuid="abc")
        self.assertEqual(diagnostics.receiver_report(dlna_renderer=dlna),
                         {"protocol": "dlna", "model": "BRAVIA X"})
        self.assertEqual(diagnostics.receiver_report(cast_device=cast),
                         {"protocol": "cast", "model": "Chromecast HD", "manufacturer": "Google Inc."})
        for report in (diagnostics.receiver_report(dlna_renderer=dlna),
                       diagnostics.receiver_report(cast_device=cast)):
            self.assertNotIn("host", report)
            self.assertNotIn("name", report)

    def test_dlna_wins_when_both_are_given_and_nothing_gives_empty(self):
        dlna = SimpleNamespace(model="TV")
        cast = SimpleNamespace(model="Cast", manufacturer="G")
        self.assertEqual(diagnostics.receiver_report(dlna, cast)["protocol"], "dlna")
        self.assertEqual(diagnostics.receiver_report(), {})
        self.assertEqual(diagnostics.receiver_report(cast_device=SimpleNamespace()),
                         {"protocol": "cast", "model": "", "manufacturer": ""})

    def test_bundle_carries_the_receiver_cleaned_bounded_and_redacted(self):
        with mock.patch.object(diagnostics, "tool_version", return_value=""):
            payload = diagnostics.collect(receiver={
                "protocol": "cast", "model": "Model 192.168.1.60 " + "x" * 500,
                "manufacturer": "  Acme  ", "host": "192.168.1.60", "name": "Kitchen",
                "secret": "token"})
        receiver = payload["receiver"]
        self.assertEqual(set(receiver), {"protocol", "model", "manufacturer"})
        self.assertNotIn("192.168.1.60", receiver["model"])
        self.assertLessEqual(len(receiver["model"]), diagnostics.MAX_RECEIVER_FIELD + 1)
        self.assertEqual(receiver["manufacturer"], "Acme")

    def test_invalid_receiver_input_never_breaks_the_bundle(self):
        for bad in (None, [], "tv", 5, {"protocol": "airplay", "model": 7}):
            with self.subTest(bad=bad), \
                 mock.patch.object(diagnostics, "tool_version", return_value=""):
                receiver = diagnostics.collect(receiver=bad)["receiver"]
                self.assertNotIn("protocol", receiver)      # only cast/dlna accepted
                self.assertNotIn("model", receiver)

    def test_gui_diagnostics_action_passes_the_active_receiver(self):
        source = (ROOT / "src" / "cast_lifecycle.py").read_text("utf-8")
        self.assertIn("diagnostics.receiver_report(self._dlna_renderer()", source)
        self.assertIn("receiver=receiver", source)


class TemplateAndDocTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / ".github/ISSUE_TEMPLATE/device-report.yml").read_text("utf-8")
        self.doc = (ROOT / "docs/DEVICE_COMPATIBILITY.md").read_text("utf-8")

    def test_template_collects_the_comparable_fields(self):
        for field_id in ("receiver", "protocol", "firmware", "version", "platform",
                         "media", "works", "problems", "diagnostics"):
            self.assertIn(f"id: {field_id}", self.template)
        for needle in ("Google Cast", "DLNA / UPnP", "smoothcast --version",
                       "smoothcast --diagnostics", "required: true"):
            self.assertIn(needle, self.template)

    def test_every_tested_behaviour_in_the_form_has_a_column_in_the_table(self):
        header = next(line for line in self.doc.splitlines() if line.startswith("| Receiver"))
        for column in ("Protocol", "Firmware", "SmoothCast", "Computer OS", "Direct play",
                       "Transcode", "Pause / seek", "Subtitles", "Volume", "Report"):
            self.assertIn(column, header)
        for behaviour in ("Direct play started", "Transcoded (HLS) play started",
                          "Pause and resume", "Seek", "Subtitles", "Volume control"):
            self.assertIn(behaviour, self.template)

    def test_doc_does_not_claim_any_verified_device_and_links_the_form(self):
        self.assertIn("No verified receivers yet", self.doc)
        self.assertIn("template=device-report.yml", self.doc)
        self.assertIn("not a guarantee", self.doc)
        readme = (ROOT / "README.md").read_text("utf-8")
        self.assertIn("docs/DEVICE_COMPATIBILITY.md", readme)

    def test_blank_issues_stay_disabled_so_reports_use_the_form(self):
        config = (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text("utf-8")
        self.assertIn("blank_issues_enabled: false", config)


if __name__ == "__main__":
    unittest.main()
