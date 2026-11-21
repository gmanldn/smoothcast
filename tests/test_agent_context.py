"""Agent-context routing is bounded, deterministic and completely headless."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_agent_context", ROOT / "scripts" / "agent_context.py"
)
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)


class AgentContextTests(unittest.TestCase):
    def test_routes_common_tasks_to_relevant_first_guide(self):
        cases = [
            (["P0", "issue", "worktree", "PR"], "workflow"),
            (["pytest", "CI", "focus", "Xvfb"], "testing"),
            (["src/cast_av.py", "subtitles"], "architecture"),
            (["src/streamer.py", "ffmpeg"], "architecture"),
            (["Caveman", "token", "cost"], "efficiency"),
        ]
        for words, expected in cases:
            with self.subTest(words=words):
                self.assertEqual(router.route(words)[0], expected)

    def test_unmatched_tasks_get_navigation_not_full_archive(self):
        self.assertEqual(router.route([]), [])
        self.assertEqual(router.route(["unknownwordxyz"]), [])
        hint = router.route_hint(["unknownwordxyz"])
        self.assertIn("docs/agents/README.md", hint)
        self.assertNotIn("docs/AGENT_REFERENCE.md", hint)

    def test_routes_are_short_and_do_not_load_source(self):
        with mock.patch.object(Path, "read_text",
                               side_effect=AssertionError("route read a file")):
            output = router.route_hint(["src/cast_queue.py", "DLNA"])
        self.assertIn("docs/agents/architecture.md", output)
        self.assertLess(len(output), router.MAX_HINT_CHARS)

    def test_list_and_read_are_bounded_and_use_only_known_topics(self):
        names = router.list_topics()
        self.assertLess(len(names), router.MAX_HINT_CHARS)
        for name in router.TOPICS:
            with self.subTest(name=name):
                path = router.guide(name)
                self.assertEqual(path.parent, ROOT / "docs" / "agents")
                self.assertTrue(path.is_file())
                self.assertLessEqual(len(path.read_text("utf-8")),
                                     router.MAX_READ_CHARS)
        with self.assertRaises(ValueError):
            router.guide("../AGENT_REFERENCE")

    def test_cli_uses_no_gui_and_never_truncates_oversized_guides(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(router.main(["route", "audio", "subtitles"]), 0)
        self.assertIn("architecture.md", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        with mock.patch.object(Path, "read_text", return_value="x" * 9000):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(router.main(["read", "testing"]), 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("refusing lossy truncation", stderr.getvalue())

    def test_path_routes_show_guarding_safety_invariants(self):
        hint = router.route_hint(["src/stream_watchdog.py", "stalled"])
        self.assertIn("INV-002", hint)
        self.assertIn("docs/INVARIANTS.md", hint)
        other = router.route_hint(["src/direct_probe.py"])
        self.assertIn("INV-003", other)
        self.assertNotIn("INV-001", other)

    def test_no_network_child_process_or_ui_imports(self):
        source = (ROOT / "scripts" / "agent_context.py").read_text("utf-8")
        for forbidden in ("import gi", "import requests", "import subprocess",
                          "import socket", "exec(", "eval(", "Popen("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
