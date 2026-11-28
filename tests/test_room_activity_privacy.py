"""#332: the room activity timeline is private to this host and never leaves it by default."""
from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import diagnostics
import room_activity

NETWORK = {"urllib", "urllib.request", "http.client", "requests", "socket", "ftplib", "smtplib", "xmlrpc"}


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("name", ["room_activity.py", "reliability_metrics.py"])
def test_activity_and_metrics_modules_have_no_network_capability(name):
    assert not imports(ROOT / "src" / name) & NETWORK


def test_the_room_feed_is_not_part_of_the_default_diagnostics_bundle():
    bundle = diagnostics.collect()
    assert bundle["activity"] == []          # nothing unless the user's export passes the console lines
    assert not {"room_feed", "room_activity", "timeline"} & set(bundle)


def test_only_the_users_explicit_export_menu_action_collects_diagnostics():
    callers = []
    for path in (ROOT / "src").glob("*.py"):
        if path.name != "diagnostics.py" and "diagnostics.export(" in path.read_text("utf-8"):
            callers.append(path.name)
    assert callers == ["cast_lifecycle.py"]  # a menu action; nothing sends it anywhere
    from gui_source import legacy_self
    body = legacy_self((ROOT / "src" / "cast_lifecycle.py").read_text("utf-8"))
    assert 'self.toast("Collecting diagnostics…")' in body


@pytest.mark.parametrize("status", list(range(-5, 700)) + [None, "403", 4.5, True])
def test_rejection_reasons_are_a_fixed_coarse_vocabulary_whatever_the_response(status):
    try:
        reason = room_activity.reason_for_status(status)  # type: ignore[arg-type]
    except TypeError:
        return  # non-int garbage is refused outright, never echoed
    assert reason in {"permission", "conflict", "busy", "unavailable", "error"}


def test_a_permission_rejection_never_carries_receiver_text():
    canary = "Living Room TV 192.168.1.77 /home/me/film.mkv"
    assert canary not in room_activity.reason_for_status(403)
    assert room_activity.reason_for_status(403) == "permission"
