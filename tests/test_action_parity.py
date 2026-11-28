"""Action parity ratchet (#458 slice 1): the registry equals what each surface really offers.

Fails when a surface gains or loses an action without the registry (and, for a
new gap, an explained KNOWN_GAPS entry) being updated, and when a gap is closed
without removing its entry.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import actions
import portal_commands
import shortcut_map

# Identifiers that exist on a surface but are not user playback actions.
NOT_PLAYBACK = {
    "mpris": {"Raise", "Quit", "OpenUri"},
    "desktop": {"help", "open", "add-files", "shortcuts", "preferences", "quit"},
    "cli": {"cast", "status", "diagnose"},  # diagnose writes a support bundle
}

KNOWN_GAPS = {
    ("volume", "mpris"): "Volume is a D-Bus property, not a method; set through the player Volume property",
    ("volume", "cli"): "no headless volume command yet",
    ("mute", "mpris"): "MPRIS has no mute; mute is a volume of 0",
    ("mute", "cli"): "no headless mute command yet",
    ("next", "cli"): "the CLI controls a receiver, not the room queue",
    ("previous", "cli"): "the CLI controls a receiver, not the room queue",
    **{(name, surface): "queue editing exists as widgets on the desktop and in the room API only"
       for name in ("queue_play", "queue_remove", "queue_move", "queue_next", "queue_clear",
                    "queue_vote", "queue_add_key")
       for surface in ("desktop", "mpris", "cli")},
    ("music_autogain", "desktop"): "a Preferences switch, not a named action",
    ("music_autogain", "mpris"): "not a transport action",
    ("music_autogain", "cli"): "not a transport action",
}


def _set_literal_with(path: Path, *needles: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Set) and all(isinstance(e, ast.Constant) for e in node.elts):
            values = {e.value for e in node.elts}
            if all(n in values for n in needles):
                return values
    raise AssertionError(f"no set literal with {needles} in {path.name}")


def _tuple_assignment(path: Path, name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets):
            return {e.value for e in node.value.elts}
    raise AssertionError(name)


def real_identifiers() -> dict[str, set[str]]:
    portal_source = (ROOT / "src/portal.py").read_text(encoding="utf-8")
    assert "action not in actions.WEB_ACTIONS" in portal_source, "portal must use the registry allowlist"
    # The page's own buttons are the independent witness of what the room offers.
    buttons = set(re.findall(r'data-action="([a-z_]+)"', portal_source))
    assert buttons <= actions.WEB_ACTIONS, sorted(buttons - actions.WEB_ACTIONS)
    assert set(portal_commands.ACTIONS) <= actions.WEB_ACTIONS
    web = set(actions.WEB_ACTIONS)
    accels = set(re.findall(r'set_accels_for_action\("app\.([a-z-]+)"',
                            (ROOT / "src/cast_control.py").read_text(encoding="utf-8")))
    desktop = {item.action for item in shortcut_map.SHARED} | accels
    mpris = set(re.findall(r'<method name="([A-Za-z]+)"', (ROOT / "src/mpris.py").read_text(encoding="utf-8")))
    cli = _tuple_assignment(ROOT / "src/cli_control.py", "COMMANDS")
    found = {"web": web, "desktop": desktop, "mpris": mpris, "cli": cli}
    return {s: ids - NOT_PLAYBACK.get(s, set()) for s, ids in found.items()}


def test_registry_matches_every_real_surface():
    real = real_identifiers()
    for surface in actions.SURFACES:
        declared = {i for a in actions.REGISTRY for i in a.on(surface)}
        assert declared == real[surface], (
            f"{surface}: registry-only {sorted(declared - real[surface])}, "
            f"surface-only {sorted(real[surface] - declared)}")


def test_gaps_are_intentional_and_explained():
    found = set(actions.gaps())
    assert found == set(KNOWN_GAPS), (
        f"new gaps {sorted(found - set(KNOWN_GAPS))}; closed gaps to remove {sorted(set(KNOWN_GAPS) - found)}")
    assert all(reason.strip() for reason in KNOWN_GAPS.values())


def test_ids_are_unique_and_labelled():
    ids = [a.id for a in actions.REGISTRY]
    assert len(ids) == len(set(ids)) and all(a.label for a in actions.REGISTRY)
    assert actions.BY_ID["play_pause"].on("mpris") == ("Play", "Pause", "PlayPause")


def test_every_entry_declares_description_icon_capability_and_permission():
    import action_state
    predicates = {name for name in dir(action_state) if name.startswith("can_")}
    for a in actions.REGISTRY:
        assert a.description and a.icon, a.id
        assert a.permission == actions.PARTICIPANT, a.id
        assert a.capability in (predicates | {""}), a.id
        if a.capability:
            assert callable(getattr(action_state, a.capability))


def test_transport_actions_share_the_state_capability_predicates():
    # The registry names the same predicate the room handler evaluates.
    assert actions.BY_ID["play_pause"].capability == "can_play_pause"
    assert actions.BY_ID["stop"].capability == "can_stop"
    assert actions.BY_ID["seek"].capability == "can_seek"
    assert actions.BY_ID["volume"].capability == actions.BY_ID["mute"].capability == "can_volume"


def test_print_parity_table(capsys):
    with capsys.disabled():
        print("\naction parity (X = offered):")
        for a in actions.REGISTRY:
            print(f"  {a.id:15s} " + " ".join(f"{s}={'X' if a.on(s) else '-'}" for s in actions.SURFACES))
