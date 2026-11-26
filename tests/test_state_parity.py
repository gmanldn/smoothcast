"""Desktop ⇄ web state parity ratchet (#628).

The declared table in ``state_parity`` must equal the fields the desktop
publishes in ``cast_portal._portal_handle`` and must cover every field the room
change-detector observes. A representative desktop state then round-trips
through ``portal_status.PublishedStatus`` unchanged, with source-time position,
queue revision and target preserved. No GTK, no receiver, no sleeps.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import portal_status
import state_parity


def _state_subscripts(target: ast.AST) -> set[str]:
    """String keys stored into ``state[...]`` for a (possibly tuple) target."""
    found: set[str] = set()
    if isinstance(target, ast.Tuple):
        for element in target.elts:
            found |= _state_subscripts(element)
    elif (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
          and target.value.id == "state"
          and isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
        found.add(target.slice.value)
    return found


def desktop_published_keys() -> set[str]:
    """The status-document keys the desktop builds in ``cast_portal._portal_handle``."""
    tree = ast.parse((ROOT / "src/cast_portal.py").read_text(encoding="utf-8"))
    handle = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_portal_handle")
    keys: set[str] = set()
    for node in ast.walk(handle):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            keys |= _state_subscripts(target)
            if (isinstance(target, ast.Name) and target.id == "state"
                    and isinstance(node.value, ast.Dict)):
                keys |= {key.value for key in node.value.keys
                         if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return keys


def web_observed_keys() -> set[str]:
    """The fields the room change-detector treats as part of the snapshot."""
    tree = ast.parse((ROOT / "src/portal.py").read_text(encoding="utf-8"))
    event_key = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == "_event_key")
    for node in ast.walk(event_key):
        if (isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "fields" for t in node.targets)):
            return {child.value for child in ast.walk(node.value)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)}
    raise AssertionError("no `fields = ...` assignment in portal._event_key")


DESKTOP_STATE = {
    "cast_feedback": None,
    "title": "Film.mkv",
    "receiver": "Living Room TV",
    "state": "PLAYING",
    "state_label": "Playing",
    "state_short": "Playing",
    "state_description": "Media is playing on the receiver",
    "state_icon": "media-playback-start-symbolic",
    "position": 62.5,
    "duration": 899.0,
    "media_kind": "video",
    "rate": 1.0,
    "volume": 42,
    "queue": [{"id": "abc123", "title": "Next.mp3", "duration": 30.0}],
    "queue_total": 0,
    "queue_revision": 7,
    "library_copies": [],
    "active": True,
    "busy": False,
    "preparing": False,
    "can_stop": True,
    "can_play_pause": True,
    "can_seek": True,
    "music_autogain": False,
    "accent": "default",
    "network_activity": [],
    "session_id": "sess-1",
    "revision": 12,
}


def test_table_matches_the_desktop_status_document():
    published = desktop_published_keys()
    assert published, "could not read the desktop status document"
    assert state_parity.keys() == published, (
        f"undeclared desktop fields {sorted(published - state_parity.keys())}; "
        f"stale table entries {sorted(state_parity.keys() - published)}")


def test_web_change_detector_observes_only_declared_fields():
    observed = web_observed_keys()
    assert observed, "could not read the room change detector"
    assert observed <= state_parity.keys(), sorted(observed - state_parity.keys())


def test_every_field_names_a_source_units_clock_and_null_meaning():
    for field in state_parity.FIELDS:
        assert field.desktop and field.units and field.null, field.snapshot
        assert field.clock in {"source", "source/wall", "none"}, field.snapshot
    assert len(state_parity.FIELDS) == len(state_parity.BY_KEY)


def test_fixture_state_round_trips_through_the_published_snapshot():
    assert set(DESKTOP_STATE) == state_parity.keys()
    snapshot = portal_status.PublishedStatus()
    version = snapshot.publish(DESKTOP_STATE)
    read = snapshot.read()
    assert read is not None
    assert read["snapshot_version"] == version
    for field in state_parity.FIELDS:
        assert read[field.snapshot] == DESKTOP_STATE[field.snapshot], field.snapshot
    # Source-time position, queue revision and target survive as authoritative.
    assert read["position"] == 62.5
    assert read["queue_revision"] == 7
    assert read["receiver"] == "Living Room TV"


def test_republishing_advances_the_version_without_mutating_the_previous_read():
    snapshot = portal_status.PublishedStatus()
    first = snapshot.publish(DESKTOP_STATE)
    earlier = snapshot.read()
    second = snapshot.publish({**DESKTOP_STATE, "queue_revision": 8})
    assert second > first
    current = snapshot.read()
    assert current["queue_revision"] == 8
    # A snapshot read earlier is a detached copy and never changes in place.
    assert earlier["queue_revision"] == 7
