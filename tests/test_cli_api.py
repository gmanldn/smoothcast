"""#434: `smoothcast house ...` against a real loopback portal."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import house_cli
from test_room_conformance import PIN, RoomHarness

KEY_A, KEY_B = "qh:" + "a" * 32, "qh:" + "b" * 32


def item(key, title, **kw):
    return {"id": key, "title": title, "year": 2017, "artist": None, "album": None,
            "copies": [{"origin": "local", "origin_name": "Study PC", "online": True}], **kw}


@pytest.fixture
def harness():
    harness = RoomHarness(count=1)
    results = {"paddington": [item(KEY_A, "Paddington 2")],
               "film": [item(KEY_A, "Paddington 2"), item(KEY_B, "Film Two")]}

    def search(text, limit=50, cursor=None):
        found = next((v for k, v in results.items() if k in text.lower()), [])
        return {"q": text, "partial": False, "next": None,
                "groups": [{"type": "films", "items": found}] if found else []}

    harness.server.library_search = search
    yield harness
    harness.close()


def run(harness, *argv):
    host = f"127.0.0.1:{harness.server.server_address[1]}"
    return house_cli.main(["--host", host, "--pin", PIN, *argv])


def test_status_prints_one_readable_line(harness, capsys):
    assert run(harness, "status") == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    assert "Current film" in out and "in Up Next" in out


def test_search_lists_ids_titles_and_where_they_live(harness, capsys):
    assert run(harness, "search", "paddington") == 0
    out = capsys.readouterr().out
    assert KEY_A in out and "Paddington 2" in out and "[Study PC]" in out


def test_add_takes_the_single_match_and_queues_it_by_key(harness, capsys):
    assert run(harness, "add", "paddington") == 0
    assert harness.calls[-1][0] == "queue_add_key" and harness.calls[-1][1]["key"] == KEY_A


def test_add_refuses_ambiguity_unless_first(harness, capsys):
    assert run(harness, "add", "film") == 1
    err = capsys.readouterr().err
    assert "More than one match" in err and KEY_B in err
    before = len(harness.calls)
    assert run(harness, "add", "film", "--first") == 0
    assert harness.calls[-1][1]["key"] == KEY_A and len(harness.calls) > before


def test_add_with_no_match_exits_nonzero(harness, capsys):
    assert run(harness, "add", "zzz") == 1
    assert "Nothing in the house matches" in capsys.readouterr().err


def test_wrong_pin_and_unreachable_host_have_friendly_exit_codes(harness, capsys):
    host = f"127.0.0.1:{harness.server.server_address[1]}"
    assert house_cli.main(["--host", host, "--pin", "000000", "status"]) == 3
    assert "PIN" in capsys.readouterr().err
    assert house_cli.main(["--host", "127.0.0.1:9", "status"]) == 3
    assert "Couldn't reach SmoothCast" in capsys.readouterr().err


def test_missing_host_explains_how_to_choose_one(capsys, monkeypatch):
    monkeypatch.delenv("SMOOTHCAST_HOST", raising=False)
    assert house_cli.main(["status"]) == 2
    assert "--host" in capsys.readouterr().err


def test_entry_point_routes_house_without_gtk(monkeypatch, capsys):
    import cli
    monkeypatch.setattr(sys, "argv", ["smoothcast", "house", "status"])
    monkeypatch.delenv("SMOOTHCAST_HOST", raising=False)
    assert cli.main() == 2
