"""Agent instruction budgets and skills; no app import, GTK or subprocess."""
import ast
from pathlib import Path
import unittest

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]


class AgentTokenEfficiencyTests(unittest.TestCase):
    def test_root_is_small_and_routes_to_a_tiered_handbook(self):
        compact = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        original = (ROOT / "docs/AGENT_REFERENCE.md").read_text(encoding="utf-8")
        self.assertLess(len(compact), 2500, "Root AGENTS must stay essentials-only")
        self.assertGreater(len(original), 30000, "Full original notes were lost")
        for required in (
            "docs/agents/README.md",
            "docs/agents/workflow.md",
            "docs/agents/testing.md",
            "docs/agents/architecture.md",
            "docs/agents/efficiency.md",
            "docs/AGENT_REFERENCE.md",
            "docs/ISSUES.md",
            ".kilo/skills/caveman/SKILL.md",
            ".kilo/skills/ponytail/SKILL.md",
            "src/version.py",
            "python3 -m pytest -q tests",
            "scripts/test_gui_isolated.py",
            "Never launch the real GUI",
        ):
            with self.subTest(required=required):
                self.assertIn(required, compact)
        for historical in ("Startup responsiveness", "Audio track identity",
                           "Single-instance", "GtkBox min > natural"):
            with self.subTest(historical=historical):
                self.assertIn(historical, original)

    def test_handbook_is_hierarchical_and_all_links_resolve(self):
        import re
        files = [
            ROOT / "AGENTS.md",
            *(ROOT / "docs" / "agents").glob("*.md"),
        ]
        self.assertEqual(len(files), 6, "Expected root plus five handbook pages")
        index = (ROOT / "docs/agents/README.md").read_text("utf-8")
        for page in ("workflow.md", "testing.md", "architecture.md",
                     "efficiency.md"):
            self.assertIn(page, index)
        for file in files:
            with self.subTest(file=str(file.relative_to(ROOT))):
                body = file.read_text("utf-8")
                for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
                    if target.startswith(("https://", "http://", "#")):
                        continue
                    link_path = (file.parent / target.split("#")[0]).resolve()
                    self.assertTrue(link_path.is_file(),
                                    f"{file}: broken handbook link {target}")

    def test_domain_guidance_is_preserved_in_child_docs(self):
        workflow = (ROOT / "docs/agents/workflow.md").read_text("utf-8")
        testing = (ROOT / "docs/agents/testing.md").read_text("utf-8")
        architecture = (ROOT / "docs/agents/architecture.md").read_text("utf-8")
        efficiency = (ROOT / "docs/agents/efficiency.md").read_text("utf-8")
        for word in ("claim", "worktree", "close", "src/version.py"):
            self.assertIn(word, workflow)
        for word in ("focus", "Xvfb", "pytest", "DBus"):
            self.assertIn(word, testing)
        for name in ("cast_control.py", "cast_ui.py", "cast_queue.py",
                     "cast_session.py", "cast_av.py", "cast_lifecycle.py",
                     "cast_widgets.py", "tests/gui_source.py"):
            self.assertIn(name, architecture)
        for word in ("Caveman", "Ponytail", "provider tokens"):
            self.assertIn(word, efficiency)

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
