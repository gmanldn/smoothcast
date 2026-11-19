"""Contracts for the lint, coverage, dependency-update and policy files."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text("utf-8")


class QualityGateTests(unittest.TestCase):
    def test_ruff_is_configured_and_gated_in_ci(self):
        self.assertIn("[tool.ruff.lint]", read("pyproject.toml"))
        workflow = read(".github/workflows/verify.yml")
        self.assertIn("ruff check src scripts setup tests sc.py setup.py", workflow)
        self.assertIn("ruff", read("pyproject.toml").split("dev = [", 1)[1].split("]", 1)[0])

    def test_coverage_runs_on_primary_python_with_a_threshold(self):
        workflow = read(".github/workflows/verify.yml")
        self.assertIn("--cov=src", workflow)
        self.assertIn("--cov-fail-under=38", workflow)
        # The full suite must still run unchanged on the Python floor.
        self.assertIn("if: matrix.python-version != '3.13'", workflow)
        self.assertIn("pytest-cov", read("pyproject.toml"))

    def test_dependabot_covers_pip_and_actions_weekly_against_develop(self):
        config = read(".github/dependabot.yml")
        for needle in ("package-ecosystem: pip", "package-ecosystem: github-actions",
                       "interval: weekly", "target-branch: develop"):
            self.assertIn(needle, config)

    def test_precommit_mirrors_ci_and_stays_headless(self):
        config = read(".pre-commit-config.yaml")
        self.assertIn("id: ruff", config)
        self.assertIn("compileall -q src scripts setup tests", config)
        self.assertNotIn("test_gui_isolated", config)

    def test_policy_files_exist_and_point_at_the_issue_workflow(self):
        self.assertIn("docs/ISSUES.md", read("CONTRIBUTING.md"))
        self.assertIn("security/advisories/new", read("SECURITY.md"))
        template = read(".github/PULL_REQUEST_TEMPLATE.md")
        for field in ("Verification class", "Real device", "Isolated GTK"):
            self.assertIn(field, template)



class DependencyGateTests(unittest.TestCase):
    def test_catt_bound_is_identical_everywhere_and_capped(self):
        bound = "catt>=0.12,<0.14"
        self.assertIn(bound, read("pyproject.toml"))
        self.assertIn(bound, read("setup/bootstrap.py"))

    def test_codeql_and_pip_audit_run_in_ci(self):
        codeql = read(".github/workflows/codeql.yml")
        for needle in ("languages: python", "pull_request:", "security-events: write"):
            self.assertIn(needle, codeql)
        self.assertIn("pip_audit", read(".github/workflows/verify.yml"))



class TypeCheckGateTests(unittest.TestCase):
    def test_mypy_is_configured_with_an_explicit_module_list_and_gated(self):
        config = read("pyproject.toml")
        self.assertIn("[tool.mypy]", config)
        self.assertIn('"src/server.py"', config)
        self.assertIn("mypy", config.split("dev = [", 1)[1].split("]", 1)[0])
        workflow = read(".github/workflows/verify.yml")
        self.assertIn("run: mypy", workflow)
        self.assertIn("Types (#251)", read("docs/agents/testing.md"))

    def test_gated_modules_exist(self):
        import re
        block = read("pyproject.toml").split("[tool.mypy]", 1)[1].split("]", 1)[0]
        listed = re.findall(r'"(src/[a-z_]+\.py)"', block)
        self.assertGreaterEqual(len(listed), 5)
        for name in listed:
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
