"""Agent instruction budgets and skills; no app import, GTK or subprocess."""
import ast
from pathlib import Path
import unittest

from gui_source import main_window_methods

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

    def test_gui_modules_stay_small_enough_to_read_narrowly(self):
        # A single 200 KB window module forced agents to grep and read a whole
        # file per task. Keep each concern in a file small enough to read.
        limits = {
            "cast_control.py": 25_000,
            "cast_widgets.py": 32_000,
            "cast_ui.py": 62_000,
            "cast_queue.py": 36_000,
            "cast_session.py": 48_000,
            "cast_av.py": 28_000,
            "cast_lifecycle.py": 16_000,
        }
        for name, limit in limits.items():
            with self.subTest(module=name):
                path = ROOT / "src" / name
                self.assertTrue(path.exists(), f"{name} is missing from the split GUI")
                self.assertLess(
                    path.stat().st_size, limit,
                    f"{name} is regrowing; split or trim it instead",
                )

    def test_main_window_is_assembled_from_the_mixins(self):
        source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
        window = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        own = [m.name for m in window.body if isinstance(m, ast.FunctionDef)]
        self.assertEqual(own, ["__init__"], "MainWindow should only define __init__")
        bases = [b.id for b in window.bases if isinstance(b, ast.Name)]
        self.assertEqual(
            bases[:5],
            ["UiMixin", "QueueMixin", "SessionMixin", "AvMixin", "LifecycleMixin"],
        )

    def test_gui_source_helper_still_sees_every_main_window_method(self):
        methods = main_window_methods()
        for name in ("_build_ui", "_cast_path", "_on_close", "toggle_play", "seek_to"):
            with self.subTest(method=name):
                self.assertIn(name, methods)
        self.assertGreaterEqual(len(methods), 148)


if __name__ == "__main__":
    unittest.main()
