"""Offline checks for the advisory issue body-size report (#516)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "issue_body_budget", ROOT / "scripts" / "ci" / "issue_body_budget.py"
)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def test_skips_epics_closed_issues_and_pull_requests():
    data = [
        {"number": 1, "body": "a" * 6001, "labels": [{"name": "epic"}]},
        {"number": 2, "body": "a" * 6001, "title": "[EPIC] scope"},
        {"number": 3, "body": "a" * 6001, "pull_request": {}},
        {"number": 4, "body": "a" * 6001, "state": "closed"},
        {"number": 5, "body": "a" * 6000},
        {"number": 6, "body": "a" * 6001},
    ]
    result = budget.inspect(data)
    assert result == {"limit_bytes": 6000, "checked": 2, "skipped": 4,
                      "oversized_count": 1,
                      "oversized": [{"number": 6, "body_bytes": 6001}]}


def test_counts_utf8_bytes_not_characters_and_sorts_biggest_first():
    result = budget.inspect([
        {"number": 9, "body": "é" * 3001},
        {"number": 3, "body": "x" * 9000},
    ])
    assert [item["number"] for item in result["oversized"]] == [3, 9]
    assert result["oversized"][1]["body_bytes"] == 6002
    assert "é" not in json.dumps(result, ensure_ascii=False)


def test_rejects_malformed_issue_metadata_and_limits():
    for issues in ([{}], [{"number": 1, "body": []}],
                   [{"number": 1, "labels": [object()]}]):
        with pytest.raises(budget.BudgetError):
            budget.inspect(issues)
    with pytest.raises(budget.BudgetError):
        budget.inspect([], 0)


def test_offline_cli_stays_advisory_and_redacts_bodies(tmp_path, capsys):
    source = tmp_path / "issues.json"
    source.write_text(json.dumps([{"number": 17, "body": "PRIVATE" * 2000}]), encoding="utf-8")
    assert budget.main(["--input", str(source)]) == 0
    printed = capsys.readouterr().out
    assert "#17: 14000 bytes" in printed
    assert "PRIVATE" not in printed
    assert budget.main(["--input", str(source), "--json"]) == 0
    assert "PRIVATE" not in capsys.readouterr().out


def test_fetch_requires_token_before_network():
    with mock.patch.object(budget.urllib.request, "urlopen") as urlopen:
        with pytest.raises(budget.BudgetError, match="GITHUB_TOKEN"):
            budget.fetch_open_issues("gmanldn/smoothcast", "")
        urlopen.assert_not_called()


def test_cli_rejects_non_list_json_without_throwing(tmp_path, capsys):
    source = tmp_path / "issues.json"
    source.write_text("{}", encoding="utf-8")
    assert budget.main(["--input", str(source)]) == 2
    assert "JSON list" in capsys.readouterr().err
