"""Headless, fail-closed CI verdict: no real GitHub queries or desktop."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_head_verdict", ROOT / "scripts" / "ci" / "head_verdict.py"
)
assert SPEC is not None and SPEC.loader is not None
verdict = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verdict)
HEAD = "a" * 40
NEW_HEAD = "b" * 40


def _job(name: str, conclusion: str = "success", status: str = "completed"):
    return {"name": name, "status": status, "conclusion": conclusion}


def _verify(*, status="completed", conclusion="success", sha=HEAD):
    return {
        "name": verdict.VERIFY, "id": 123, "run_attempt": 1,
        "head_sha": sha, "head_branch": "develop", "event": "push",
        "status": status, "conclusion": conclusion,
        "html_url": "https://github.com/gmanldn/smoothcast/actions/runs/123",
    }


def _external(name: str, *, status="completed", conclusion="success"):
    return {
        "name": name, "id": 124 if name == "CodeQL" else 125,
        "head_sha": HEAD, "head_branch": "develop", "event": "push",
        "status": status, "conclusion": conclusion,
    }


def _jobs(promote="skipped"):
    return [_job(name) for name in sorted(verdict.REQUIRED)] + [
        _job("Portable regressions (Python)", "skipped"),
        _job(verdict.PROMOTION, promote),
    ]


def _api(*, runs=None, jobs=None, changed=False, missing=False):
    calls = []
    def read(path):
        calls.append(path)
        if path.endswith("/git/ref/heads/develop"):
            if missing:
                raise verdict.VerdictError("develop deleted")
            return {"object": {"sha": NEW_HEAD if changed and calls.count(path) > 1
                                else HEAD}}
        if "/actions/runs?" in path:
            return {"workflow_runs": runs if runs is not None else [
                _verify(), _external("CodeQL"),
                _external("Portal Security Regressions"),
            ]}
        if "/jobs?" in path:
            return {"jobs": jobs if jobs is not None else _jobs()}
        raise AssertionError(f"unexpected API request: {path}")
    read.calls = calls
    return read


class VerdictTests(unittest.TestCase):
    def test_exact_head_all_triggered_checks_green(self):
        api = _api()
        result = verdict.inspect(api=api)
        self.assertEqual(result["verdict"], "green")
        self.assertEqual(result["software"], "passed")
        self.assertEqual(result["release"], "not_required")
        self.assertEqual(result["run"], 123)
        self.assertEqual(result["checks"], {
            "CodeQL": "passed", "Portal Security Regressions": "passed",
        })
        self.assertEqual(api.calls[0], api.calls[-1])
        self.assertEqual(len(api.calls), 4)

    def test_release_success_is_distinct_from_skipped(self):
        result = verdict.inspect(api=_api(jobs=_jobs("success")))
        self.assertEqual(result["release"], "passed")
        self.assertEqual(result["verdict"], "green")

    def test_release_only_failure_never_returns_green(self):
        result = verdict.inspect(api=_api(
            runs=[_verify(conclusion="failure"), _external("CodeQL")],
            jobs=_jobs("failure"),
        ))
        self.assertEqual(result["software"], "passed")
        self.assertEqual(result["release"], "blocked")
        self.assertEqual(result["verdict"], "failed")
        self.assertIn("Promote", " ".join(result["blockers"]))

    def test_required_gate_failure_blocks_verification(self):
        jobs = _jobs()
        jobs[0]["conclusion"] = "failure"
        result = verdict.inspect(api=_api(jobs=jobs))
        self.assertEqual(result["software"], "failed")
        self.assertEqual(result["verdict"], "failed")

    def test_pending_workflow_or_external_security_scan_blocks(self):
        result = verdict.inspect(api=_api(runs=[
            _verify(status="in_progress", conclusion=None),
            _external("CodeQL", status="queued", conclusion=None),
        ]))
        self.assertEqual(result["software"], "pending")
        self.assertEqual(result["verdict"], "pending")

    def test_cancelled_old_sha_is_never_accepted_as_current(self):
        result = verdict.inspect(api=_api(runs=[
            _verify(sha=NEW_HEAD), _external("CodeQL")
        ]))
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["run"], None)
        self.assertIn("no push Verify", result["blockers"][0])

    def test_develop_head_moves_during_poll(self):
        result = verdict.inspect(api=_api(changed=True))
        self.assertEqual(result["verdict"], "stale")
        self.assertIn(NEW_HEAD, result["blockers"][0])

    def test_explicit_stale_head_avoids_running_checks(self):
        api = _api()
        result = verdict.inspect(expected_sha=NEW_HEAD, api=api)
        self.assertEqual(result["verdict"], "stale")
        self.assertEqual(len(api.calls), 1)

    def test_unknown_missing_or_duplicate_job_never_passes(self):
        jobs = _jobs()
        result = verdict.inspect(api=_api(jobs=jobs[1:]))
        self.assertEqual(result["verdict"], "pending")
        with self.assertRaises(verdict.VerdictError):
            verdict.inspect(api=_api(jobs=jobs + [jobs[0]]))

    def test_deleted_branch_and_malformed_api_fail_closed(self):
        with self.assertRaises(verdict.VerdictError):
            verdict.inspect(api=_api(missing=True))
        with self.assertRaises(verdict.VerdictError):
            verdict.inspect(api=lambda _path: {"unrelated": "payload"})
        with self.assertRaises(verdict.VerdictError):
            verdict.inspect(repository="../../elsewhere", api=_api())

    def test_cli_exit_status_and_compact_json(self):
        data = verdict.inspect(api=_api())
        out, err = StringIO(), StringIO()
        with patch.object(verdict, "inspect", return_value=data):
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(verdict.main(["--json"]), 0)
        self.assertIn('"verdict":"green"', out.getvalue())
        self.assertEqual(err.getvalue(), "")
        data["verdict"] = "failed"
        with patch.object(verdict, "inspect", return_value=data):
            with redirect_stdout(StringIO()):
                self.assertEqual(verdict.main([]), 1)
