"""Known-red tests must have an owner, a ticket and an expiry (ARCH-12, #700).

`ship` stops on pre-existing red that has no live quarantine entry, so the
decision in `agent.unquarantined` and the shape of tests/quarantine.json are
the contract these tests pin. Hermetic: a temporary tree stands in for the repo.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent

REPO = Path(__file__).resolve().parents[1]
TODAY = datetime.date.today()
FUTURE = (TODAY + datetime.timedelta(days=14)).isoformat()
PAST = (TODAY - datetime.timedelta(days=1)).isoformat()


def _root_with(tmp_path, monkeypatch, entries):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "quarantine.json").write_text(json.dumps({"entries": entries}))
    monkeypatch.setattr(agent, "ROOT", tmp_path)


def _entry(**over):
    entry = {"owner": "alice", "ticket": 700, "expires": FUTURE}
    entry.update(over)
    return entry


def test_live_entry_excuses_only_its_own_test(monkeypatch, tmp_path):
    _root_with(tmp_path, monkeypatch, {"tests/a.py::t": _entry()})
    assert agent.unquarantined(["tests/a.py::t"]) == []
    assert agent.unquarantined(["tests/a.py::t", "tests/b.py::u"]) == ["tests/b.py::u"]


def test_entry_expiring_today_is_still_live(monkeypatch, tmp_path):
    _root_with(tmp_path, monkeypatch, {"tests/a.py::t": _entry(expires=TODAY.isoformat())})
    assert agent.unquarantined(["tests/a.py::t"]) == []


@pytest.mark.parametrize("label,entry", [
    ("expired", _entry(expires=PAST)),
    ("no expiry", {"owner": "alice", "ticket": 700}),
    ("blank owner", _entry(owner="   ")),
    ("no owner", {"ticket": 700, "expires": FUTURE}),
    ("no ticket", {"owner": "alice", "expires": FUTURE}),
    ("zero ticket", _entry(ticket=0)),
    ("not an object", "alice"),
    ("null entry", None),
])
def test_incomplete_or_expired_entry_excuses_nothing(monkeypatch, tmp_path, label, entry):
    _root_with(tmp_path, monkeypatch, {"tests/a.py::t": entry})
    assert agent.unquarantined(["tests/a.py::t"]) == ["tests/a.py::t"], label


@pytest.mark.parametrize("content", [None, "not json", json.dumps({"entries": "nope"}),
                                     json.dumps({"other": {}})])
def test_missing_or_corrupt_file_excuses_nothing(monkeypatch, tmp_path, content):
    (tmp_path / "tests").mkdir()
    if content is not None:
        (tmp_path / "tests" / "quarantine.json").write_text(content)
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    assert agent.unquarantined(["tests/a.py::t"]) == ["tests/a.py::t"]


def test_committed_quarantine_file_is_well_formed_and_unexpired():
    """Every committed entry names an owner, a ticket and a future date, or it is not excused."""
    entries = json.loads((REPO / "tests" / "quarantine.json").read_text())["entries"]
    problems = []
    for node, entry in entries.items():
        if "::" not in node or not (REPO / node.split("::", 1)[0]).is_file():
            problems.append(f"{node}: test file does not exist")
        if not str(entry.get("owner", "")).strip():
            problems.append(f"{node}: no owner")
        if not isinstance(entry.get("ticket"), int) or entry["ticket"] <= 0:
            problems.append(f"{node}: no ticket")
        try:
            expires = datetime.date.fromisoformat(str(entry.get("expires")))
        except ValueError:
            problems.append(f"{node}: expiry is not YYYY-MM-DD")
            continue
        if expires < TODAY:
            problems.append(f"{node}: expired {expires}; fix the test or renew with a reason")
    assert not problems, "\n".join(problems)
