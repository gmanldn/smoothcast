from contextlib import redirect_stdout
from io import StringIO
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("time_to_red", Path(__file__).resolve().parents[1] / "scripts" / "ci" / "time_to_red.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

C = "2026-11-27T10:00:00Z"


def run(sha, conclusion, at):
    return {"head_sha": sha, "conclusion": conclusion, "updated_at": at}


def test_earliest_failure_wins_and_success_is_ignored():
    runs = [run("a", "success", "2026-11-27T10:02:00Z"), run("a", "failure", "2026-11-27T10:12:30Z"), run("a", "timed_out", "2026-11-27T10:40:00Z")]
    assert T.time_to_red(C, runs) == 12.5


def test_green_commit_has_no_time_to_red():
    assert T.time_to_red(C, [run("a", "success", "2026-11-27T10:05:00Z"), run("a", "cancelled", "2026-11-27T10:06:00Z")]) is None
    assert T.time_to_red(C, []) is None


def test_clock_skew_never_goes_negative():
    assert T.time_to_red(C, [run("a", "failure", "2026-11-27T09:59:00Z")]) == 0.0


def test_summary_flags_only_runs_over_the_fifteen_minute_budget():
    commits = {"a": C, "b": C, "c": C}
    runs = [run("a", "failure", "2026-11-27T10:14:00Z"), run("b", "failure", "2026-11-27T10:15:06Z"), run("c", "success", "2026-11-27T10:03:00Z"), run("zzz", "failure", "2026-11-27T10:01:00Z")]
    s = T.summarise(commits, runs)
    assert s["values"] == {"a": 14.0, "b": 15.1, "c": None}
    assert s["red_commits"] == 2 and s["worst_min"] == 15.1 and s["over_budget"] == ["b"]


def test_empty_summary():
    assert T.summarise({}, [])["worst_min"] is None


def test_nightly_report_uses_only_push_failures_and_marks_sample_bound(tmp_path):
    commits = tmp_path / "commits.tsv"
    runs = tmp_path / "runs.tsv"
    commits.write_text(f"a\t{C}\n", encoding="utf-8")
    runs.write_text(
        "a\tfailure\t2026-11-27T10:12:30Z\tpush\n"
        "a\tfailure\t2026-11-27T10:01:00Z\tschedule\n",
        encoding="utf-8",
    )

    output = T.report(str(commits), str(runs))

    assert "Observed 1 recent commits and 1 push workflow runs" in output
    assert "worst: 12.5 min" in output
    assert "Over the 15 minute budget: none" in output
    assert "first API page" in output


def test_nightly_report_rejects_malformed_api_export(tmp_path):
    commits = tmp_path / "commits.tsv"
    runs = tmp_path / "runs.tsv"
    commits.write_text("missing timestamp\n", encoding="utf-8")
    runs.write_text("", encoding="utf-8")

    import pytest

    with pytest.raises(ValueError, match="2 tab-separated columns"):
        T.report(str(commits), str(runs))


def test_nightly_report_fails_when_observed_time_to_red_exceeds_budget(tmp_path):
    commits = tmp_path / "commits.tsv"
    runs = tmp_path / "runs.tsv"
    commits.write_text(f"a\t{C}\n", encoding="utf-8")
    runs.write_text("a\tfailure\t2026-11-27T10:16:00Z\tpush\n", encoding="utf-8")

    with redirect_stdout(StringIO()):
        result = T.main(["--commits-tsv", str(commits), "--runs-tsv", str(runs)])

    assert result == 1
