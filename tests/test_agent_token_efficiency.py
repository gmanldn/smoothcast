"""Agent instruction budgets and skills; no app import, GTK or subprocess."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AgentTokenEfficiencyTests(unittest.TestCase):
    def test_compact_root_keeps_complete_original_retrievable(self):
        compact = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        original = (ROOT / "docs/AGENT_REFERENCE.md").read_text(encoding="utf-8")
        self.assertLess(len(compact), 7500, "Global instructions are bloating again")
        self.assertGreater(len(original), 30000, "Full original agent notes were lost")
        for required in (
            "docs/AGENT_REFERENCE.md",
            ".kilo/skills/caveman/SKILL.md",
            ".kilo/skills/ponytail/SKILL.md",
            "docs/AGENT_TOKEN_EFFICIENCY.md",
            "src/version.py",
            "docs/ISSUES.md",
            "python3 -m pytest -q tests",
            "scripts/test_gui_isolated.py",
            "Do not launch/focus the real app",
        ):
            with self.subTest(required=required):
                self.assertIn(required, compact)
        for historical in ("Startup responsiveness", "Audio track identity",
                           "Single-instance", "GtkBox min > natural"):
            with self.subTest(historical=historical):
                self.assertIn(historical, original)

    def test_named_skills_are_discoverable_and_do_not_skip_correctness(self):
        for name, must_contain in (
            ("caveman", ("negation", "error", "commands", "prose")),
            ("ponytail", ("smallest", "test", "security", "callers")),
        ):
            with self.subTest(name=name):
                path = ROOT / ".kilo" / "skills" / name / "SKILL.md"
                body = path.read_text(encoding="utf-8")
                self.assertTrue(body.startswith("---\nname: " + name + "\n"))
                for detail in must_contain:
                    self.assertIn(detail, body.lower())
                self.assertLess(len(body), 2500)

    def test_no_install_or_gui_launch_required_by_agent_integration(self):
        doc = (ROOT / "docs/AGENT_TOKEN_EFFICIENCY.md").read_text("utf-8")
        self.assertIn("not enabled by this repo", doc.lower())
        self.assertIn("never start the gui", doc.lower())
        self.assertIn("not a measured model-token count", doc.lower())
        self.assertIn("provider-billed", doc.lower())


if __name__ == "__main__":
    unittest.main()
