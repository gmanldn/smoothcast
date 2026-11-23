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
        with mock.patch.object(Path, "read_text", return_value="x" * (router.MAX_READ_CHARS + 500)):
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

    def test_preview_is_not_misread_as_pr_and_named_docs_win(self):
        self.assertEqual(router.route(["preview"])[0], "architecture")
        self.assertNotIn("workflow", router.route(["preview", "player"]))
        self.assertNotIn("workflow", router.route(["improve"]))
        self.assertEqual(router.route(["PR"])[0], "workflow")
        self.assertEqual(router.route(["subtitles"])[0], "architecture")
        self.assertEqual(router.route(["docs/agents/workflow.md"])[0], "workflow")
        self.assertEqual(router.route(["docs/agents/efficiency.md"])[0], "efficiency")

    def test_root_sends_agents_to_agent_ready_issues_without_large_context(self):
        root = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("scripts/ticket_digest.py --next --label agent-ready", root)
        self.assertLess(len(root), 3000)

    def test_workflow_stays_readable_while_release_details_remain_available(self):
        guide = (ROOT / "docs/agents/workflow.md").read_text(encoding="utf-8")
        detail = (ROOT / "docs/RELEASE_FLOW.md").read_text(encoding="utf-8")
        self.assertLess(len(guide), router.MAX_READ_CHARS - 100)
        self.assertIn("../COORDINATION.md", guide)   # claim and handover protocol
        self.assertIn("promote_release.py", detail)  # historical helper stays documented
        self.assertIn("owner", detail)               # and main stays an owner-only action
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(router.main(["read", "workflow"]), 0)
        self.assertIn("Main — manual owner action only", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_no_network_child_process_or_ui_imports(self):
        source = (ROOT / "scripts" / "agent_context.py").read_text("utf-8")
        for forbidden in ("import gi", "import requests", "import subprocess",
                          "import socket", "exec(", "eval(", "Popen("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
