"""Bounded issue workflow: no network, no GUI, no second backlog."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIGEST = ROOT / "scripts" / "ticket_digest.py"

spec = importlib.util.spec_from_file_location("smoothcast_ticket_digest", DIGEST)
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


def issue(number: int, title: str, claim=(), updated="2026-11-18T10:00:00Z"):
    return digest.normalize(
        {
            "number": number,
            "title": title,
            "state": "OPEN",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": name} for name in claim],
            "updatedAt": updated,
            "url": f"https://example.invalid/issues/{number}",
        }
    )


class DigestLogicTests(unittest.TestCase):
    def test_priority_and_legacy_ids_come_from_the_title(self):
        self.assertEqual(digest.priority_of("[P0][SC-058] Fix"), "P0")
        self.assertEqual(digest.priority_of("  [P2] Trim"), "P2")
        self.assertEqual(digest.priority_of("No prefix"), "P3")
        self.assertEqual(digest.legacy_id_of("[P1][SC-132] Idea"), "SC-132")
        self.assertEqual(digest.legacy_id_of("[P1] Idea"), "")
        self.assertEqual(
            digest.display_title("[P1][SC-132] Idea"), "Idea"
        )
        self.assertEqual(digest.display_title("[P1] Idea"), "Idea")

    def test_normalize_keeps_compact_metadata_only(self):
        normalized = issue(7, " [P1][SC-007]  Title\nwith   spaces ", ("alice",))
        self.assertEqual(normalized["title"], "[P1][SC-007] Title with spaces")
        self.assertEqual(normalized["priority"], "P1")
        self.assertEqual(normalized["legacy"], "SC-007")
        self.assertEqual(normalized["claim"], ["alice"])
        self.assertEqual(normalized["labels"], ["bug"])
        self.assertNotIn("body", normalized)

    def test_filters_are_local_and_do_not_fetch_bodies(self):
        rows = [
            issue(1, "[P0] A", ("alice",)),
            issue(2, "[P1] B"),
            issue(3, "[P2] C"),
        ]
        self.assertEqual(
            [row["number"] for row in rows if digest.matches(row, ["P0", "P1"])],
            [1, 2],
        )
        self.assertEqual(
            [row["number"] for row in rows if digest.matches(row, claimed=False)],
            [2, 3],
        )
        self.assertEqual(
            [row["number"] for row in rows if digest.matches(row, claimed=True)],
            [1],
        )

    def test_next_prefers_unclaimed_then_priority_then_oldest(self):
        rows = [
            issue(10, "[P0] claimed", ("alice",), "2026-11-01T00:00:00Z"),
            issue(11, "[P1] older", (), "2026-11-02T00:00:00Z"),
            issue(12, "[P1] newer", (), "2026-11-03T00:00:00Z"),
            issue(13, "[P0] open", (), "2026-11-04T00:00:00Z"),
        ]
        chosen = digest.sort_for_next(row for row in rows if not row["claim"])[0]
        self.assertEqual(chosen["number"], 13)

    def test_listing_is_priority_first_and_one_line(self):
        rows = [issue(2, "[P2] Later"), issue(1, "[P0] First")]
        ordered = digest.sort_for_listing(rows)
        self.assertEqual([row["number"] for row in ordered], [1, 2])
        line = digest.format_issue(ordered[0])
        self.assertIn("#1 P0", line)
        self.assertIn("First", line)
        self.assertNotIn("[P0]", line)
        self.assertNotIn("\n", line)

    def test_limits_are_bounded(self):
        self.assertEqual(digest.clamp_limit(0), 1)
        self.assertEqual(digest.clamp_limit(10_000), digest.MAX_LIMIT)
        self.assertEqual(digest.clamp_scan(0), 1)
        self.assertEqual(digest.clamp_scan(10_000), digest.MAX_SCAN)

    def test_json_payload_has_no_body_field(self):
        payload = json.dumps([issue(1, "[P0] A")], separators=(",", ":"))
        self.assertNotIn('"body"', payload)
        self.assertNotIn("body", digest.LIST_FIELDS)
        self.assertNotIn("comments", digest.LIST_FIELDS)


class TicketDocumentationTests(unittest.TestCase):
    def test_workflow_points_at_the_bounded_digest(self):
        workflow = (ROOT / "docs" / "ISSUES.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "scripts/ticket_digest.py",
            "--next",
            "--show",
            "assigning yourself",
            "Query budget",
            "not** provider-billed tokens",
            "Work-unit sizing",
            "ISSUES_MIGRATION_20261118.md",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        self.assertIn("scripts/ticket_digest.py", agents)
        self.assertIn("scripts/ticket_digest.py", readme)

    def test_migration_history_is_preserved_outside_the_fast_path(self):
        migration = (ROOT / "docs" / "ISSUES_MIGRATION_20261118.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "132 numbered proposals",
            "SC-001",
            "SC-132",
            "b76579c12f6a202188cc7964a0de06c09bd5aa9e",
            "IMPROVEMENTS_ORIGINAL_50_20261118.md",
            "#28",
            "#29",
            "duplicate",
            "historical",
        ):
            with self.subTest(required=required):
                self.assertIn(required, migration)

    def test_issue_template_forces_one_compact_work_unit(self):
        template = (
            ROOT / ".github" / "ISSUE_TEMPLATE" / "improvement.md"
        ).read_text(encoding="utf-8")
        for required in (
            "Outcome",
            "Acceptance criteria",
            "Work unit",
            "Normalized units: 1",
            "Split trigger",
            "Verification class",
            "Agent notes",
        ):
            with self.subTest(required=required):
                self.assertIn(required, template)
        self.assertLess(len(template), 3_500, "Issue template is bloating")

    def test_blank_issues_are_disabled_and_docs_are_linked(self):
        config = (
            ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("blank_issues_enabled: false", config)
        self.assertIn("docs/ISSUES.md", config)
        self.assertIn("docs/AGENT_TOKEN_EFFICIENCY.md", config)

    def test_instruction_and_tool_budgets(self):
        workflow = (ROOT / "docs" / "ISSUES.md").read_text(encoding="utf-8")
        digest_source = DIGEST.read_text(encoding="utf-8")
        self.assertLess(len(workflow), 12_000, "Issue workflow is bloating again")
        self.assertLess(len(digest_source), 20_000, "Digest tool is bloating again")
        self.assertFalse((ROOT / "IMPROVEMENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
