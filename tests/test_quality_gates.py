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
        self.assertIn("ruff check src scripts setup tests smoothcast setup.py", workflow)
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
        pychromecast = "PyChromecast>=13.1.0,<15"
        self.assertIn(pychromecast, read("pyproject.toml"))
        self.assertIn(pychromecast, read("setup/bootstrap.py"))
        workflow = read(".github/workflows/verify.yml")
        for job_name, next_job in (
            ("  portable-tests:", "  portable-tests-native:"),
            ("  portable-tests-native:", "  media-integration:"),
        ):
            job = workflow.split(job_name, 1)[1].split(next_job, 1)[0]
            self.assertIn(pychromecast, job)

    def test_codeql_and_pip_audit_run_in_ci(self):
        codeql = read(".github/workflows/codeql.yml")
        for needle in ("languages: python", "schedule:", "workflow_dispatch:", "security-events: write"):
            self.assertIn(needle, codeql)  # weekly/manual by owner policy (#511); never per push
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



class FuzzGateTests(unittest.TestCase):
    def test_ci_installs_hypothesis_so_the_fuzz_tests_cannot_silently_skip(self):
        workflow = read(".github/workflows/verify.yml")
        portable = workflow.split("  portable-tests:", 1)[1].split("  media-integration:", 1)[0]
        self.assertIn("hypothesis>=6,<7", portable)
        self.assertIn("hypothesis", read("pyproject.toml"))

    def test_fuzz_runs_are_bounded_and_reproducible(self):
        source = read("tests/test_fuzz_parsers.py")
        self.assertIn("max_examples=150", source)
        self.assertIn("derandomize=True", source)
        for parser in ("decode_srt", "parse_renderer", "load_playlist", "ffprobe", "_upnp_fault"):
            self.assertIn(parser, source)



class AgentHygieneTests(unittest.TestCase):
    def test_develop_only_rule_is_first_and_loud_in_agents_md(self):
        agents = read("AGENTS.md")
        self.assertLess(agents.index("Only develop receives agent code"), agents.index("## Quality and safety"))
        for needle in ("Main is manually promoted by the owner", "Never push/merge/promote/tag main",
                       "force-push", "private detached worktree", "agent.py start", "agent.py ship",
                       "agent.py finish", "workflow.md"):
            self.assertIn(needle, agents)
        self.assertLess(len(agents), 3500)  # root stays essentials-only

    def test_workflow_documents_trunk_flow_hygiene_and_manual_main(self):
        workflow = read("docs/agents/workflow.md")
        # Concepts, not exact sentences: the doc is rewritten often.
        for needle in ("only active development", "worktree", "named files", "Refs #N",
                       "Lazy, risk-weighted CI", "Main — manual owner action only",
                       "No automatic `develop → main`", "sync_pyproject.py", "Never lose work",
                       "agent.py ship"):
            self.assertIn(needle, workflow)

    def test_no_document_still_tells_agents_to_use_feature_branches_or_agent_prs(self):
        for name in ("AGENTS.md", "CONTRIBUTING.md", "docs/ISSUES.md", "docs/agents/workflow.md"):
            text = read(name).lower()
            for stale in ("issue-specific branch", "open prs against", "every issue branch",
                          "work on a branch off", "open a pr referencing"):
                self.assertNotIn(stale, text, f"{name}: {stale}")


class CiConcurrencyTests(unittest.TestCase):
    def test_trunk_verify_is_coalesced_per_ref_and_never_interrupts_a_running_run(self):
        """#539: one running run plus the newest pending run per ref; never cancel the active one."""
        workflow = read(".github/workflows/verify.yml")
        block = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:", 1)[0]
        self.assertIn("github.ref", block)
        self.assertIn("cancel-in-progress: false", block)
        self.assertNotIn("cancel-in-progress: true", block)


class FakeReceiverDocTests(unittest.TestCase):
    def test_harness_is_documented_and_exercised_by_real_code_paths(self):
        doc = read("docs/agents/testing.md")
        for needle in ("tests/fake_receivers.py", "FakeDlnaRenderer", "FakeCast",
                       "allow_loopback", "advance(seconds)"):
            self.assertIn(needle, doc)
        usage = read("tests/test_fake_receivers.py")
        for needle in ("dlna.Session()", "start_direct", "cli_control.main", "castctl.scan()"):
            self.assertIn(needle, usage)


class NativeOsPortableTests(unittest.TestCase):
    def test_portable_suite_gates_on_macos_and_windows_headless(self):
        workflow = read(".github/workflows/verify.yml")
        job = workflow.split("  portable-tests-native:", 1)[1].split("\n  media-integration:", 1)[0]
        for needle in ("os: [macos-15, windows-2025]", "python -m pytest -q tests",
                       "pytest-xdist>=3,<4", "-n auto", "psutil"):
            self.assertIn(needle, job)
        self.assertNotIn("continue-on-error", job)             # it gates; gaps go in platform_gaps.py
        self.assertNotIn("test_gui_isolated", job)             # never a GUI
        self.assertNotIn("promote-release", workflow)           # no promotion job to gate (#579)


if __name__ == "__main__":
    unittest.main()
