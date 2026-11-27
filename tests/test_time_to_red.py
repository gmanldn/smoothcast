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
