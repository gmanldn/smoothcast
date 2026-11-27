"""Executable GTK-free Preferences contracts, not merely source substring checks.

The real methods are extracted from the source AST. Dummy widgets allow tests
to verify callback lifecycle without opening a desktop or contacting a TV.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

import picture_adjustments
import preference_choices
from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]


def extracted_preferences(*names):
    found = {}
    # PreferencesWindow inherits the picture, track and update mixins; extract
    # every contributor so a method added to any of them stays testable here.
    for module, class_name in (("preferences_picture_ui.py", "PicturePreferencesMixin"),
                               ("preferences_tracks_ui.py", "TrackPreferencesMixin"),
                               ("preferences_update_ui.py", "UpdatePreferencesMixin"),
                               ("preferences_ui.py", "PreferencesWindow")):
        source = (ROOT / "src" / module).read_text("utf-8")
        owner = next(node for node in ast.parse(source).body
                     if isinstance(node, ast.ClassDef) and node.name == class_name)
        found.update({node.name: ast.get_source_segment(source, node) for node in owner.body
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
    statements = "\n\n".join(
        textwrap.indent(textwrap.dedent(found[name]), "    ") for name in names
    )
    namespace = {
        "preference_choices": preference_choices,
        "picture_adjustments": picture_adjustments,
        "save_config": mock.Mock(),
        "GLib": SimpleNamespace(Variant=lambda fmt, value: (fmt, value)),
        "Gtk": SimpleNamespace(StringList=SimpleNamespace(new=list)),
    }
    exec(compile("class Methods:\n" + statements, "<preferences-methods>", "exec"), namespace)
    return namespace["Methods"]


def test_preferences_open_reuses_window_and_resynchronises_without_casting():
    source = main_window_methods()
    methods = "class UI:\n" + "\n".join(
        textwrap.indent(textwrap.dedent(source[name]), "    ")
        for name in ("action_preferences", "_preferences_closed")
    )
    namespace = {}
    exec(compile(methods, "<preferences-open>", "exec"), namespace)
    created = []

    class FakePreferences:
        def __init__(self, owner):
            self.owner = owner
            self.connect = mock.Mock()
            self.sync_from_owner = mock.Mock()
            self.present = mock.Mock()
            created.append(self)

    window = namespace["UI"]()
    with mock.patch.dict(sys.modules, {"preferences_ui": SimpleNamespace(PreferencesWindow=FakePreferences)}):
        window.action_preferences()
        first = created[0]
        window.action_preferences()
        assert len(created) == 1
        assert first.sync_from_owner.call_count == 2
        assert first.present.call_count == 2
        first.connect.assert_called_once()
        assert window._preferences_closed(first) is False
        window.action_preferences()
        assert len(created) == 2  # fresh view after an actual close


def test_reopening_reads_latest_config_and_updates_on_main_context():
    UI = extracted_preferences("sync_from_owner", "_sync_update_status")
    prefs = UI()
    prefs._syncing = False
    prefs._audio_labels = None
    prefs._embedded_labels = None
    prefs.audio_track = mock.Mock()
    prefs.embedded_track = mock.Mock()
    prefs.subtitle_file = mock.Mock()
    prefs.gain = mock.Mock()
    prefs.portal_port_spin = mock.Mock()
    prefs.update_status_row = mock.Mock()
    prefs._picture_spins = {"picture_brightness": mock.Mock()}
    prefs._combos = {"quality": mock.Mock(), "color_scheme": mock.Mock()}
    prefs._switches = {"direct": mock.Mock(), "auto_theme": mock.Mock()}
    owner = SimpleNamespace(
        cfg={
            "quality": "balanced", "color_scheme": "prefer-dark",
            "direct": True, "auto_theme": False,
            "audio_gain": 3.0, "subs": "off", "picture_brightness": 0.25,
        },
        media=None,
        audio_track_dropdown=SimpleNamespace(get_selected=lambda: 0),
        embedded_dropdown=SimpleNamespace(get_selected=lambda: 0),
        _subs_status_text=lambda: "No caption file",
    )
    prefs.owner = owner
    prefs._combos["quality"].set_selected.side_effect = (
        lambda index: (_ for _ in ()).throw(AssertionError("sync guard missing"))
        if not prefs._syncing else None
    )
    prefs.sync_from_owner()
    assert prefs._syncing is False
    prefs._combos["quality"].set_selected.assert_called_with(1)
    prefs._switches["direct"].set_active.assert_called_with(True)
    prefs.gain.set_value.assert_called_with(3.0)
    prefs._picture_spins["picture_brightness"].set_value.assert_called_with(
        picture_adjustments.validated("picture_brightness", 0.25))
    prefs.audio_track.set_sensitive.assert_called_with(False)
    prefs.subtitle_file.set_subtitle.assert_called_with("No caption file")
    owner.cfg.update(quality="high", direct=False, audio_gain=12.0)
    prefs.sync_from_owner()
    prefs._combos["quality"].set_selected.assert_called_with(0)
    prefs._switches["direct"].set_active.assert_called_with(False)
    prefs.gain.set_value.assert_called_with(12.0)


def test_preferences_choices_delegate_to_existing_owner_callbacks():
    UI = extracted_preferences("_change_choice", "_change_switch", "_change_gain")
    prefs = UI()
    prefs._syncing = False
    prefs.sync_from_owner = mock.Mock()
    owner = SimpleNamespace(
        cfg={"loop": False, "direct": False},
        quality_dropdown=mock.Mock(),
        direct_switch=mock.Mock(),
        _toggle_loop=mock.Mock(),
        gain_spin=mock.Mock(),
        app=SimpleNamespace(scheme_action=SimpleNamespace(activate=mock.Mock())),
    )
    prefs.owner = owner

    prefs._change_choice("quality", SimpleNamespace(get_selected=lambda: 2))
    owner.quality_dropdown.set_selected.assert_called_once_with(2)
    prefs._change_switch("direct", SimpleNamespace(get_active=lambda: True))
    owner.direct_switch.set_active.assert_called_once_with(True)
    prefs._change_switch("loop", SimpleNamespace(get_active=lambda: True))
    owner._toggle_loop.assert_called_once_with()
    prefs._change_gain(SimpleNamespace(get_value=lambda: 14.0))
    owner.gain_spin.set_value.assert_called_once_with(14.0)
    prefs._change_choice("color_scheme", SimpleNamespace(get_selected=lambda: 1))
    owner.app.scheme_action.activate.assert_called_once_with(
        ("s", preference_choices.selected_value("color_scheme", 1))
    )

    style = preference_choices.selected_index("subtitle_style", "high-contrast")
    owner.cfg = {"subtitle_style": "default"}
    prefs._change_choice("subtitle_style", SimpleNamespace(get_selected=lambda: style))
    assert owner.cfg["subtitle_style"] == "high-contrast"
    UI._change_choice.__globals__["save_config"].assert_called_once_with(owner.cfg)

    prefs._syncing = True
    prefs._change_choice("quality", SimpleNamespace(get_selected=lambda: 0))
    prefs._change_switch("direct", SimpleNamespace(get_active=lambda: False))
    prefs._change_gain(SimpleNamespace(get_value=lambda: 20))
    owner.quality_dropdown.set_selected.assert_called_once()
    owner.direct_switch.set_active.assert_called_once()
    owner.gain_spin.set_value.assert_called_once()


def test_subtitle_selection_is_opt_in_and_cancel_path_reuses_owner():
    UI = extracted_preferences("_change_choice", "_subtitle_selected")
    prefs = UI()
    prefs._syncing = False
    prefs._choose_subtitle_file = mock.Mock()
    prefs.sync_from_owner = mock.Mock()
    prefs.owner = SimpleNamespace(
        cfg={"subs": "auto"},
        _syncing=False,
        subs_dropdown=mock.Mock(),
        _subs_file_chosen=mock.Mock(),
    )
    # Choosing the file option must not silently save a bogus caption path.
    prefs._change_choice("subs", SimpleNamespace(get_selected=lambda: 2))
    prefs._choose_subtitle_file.assert_called_once()
    prefs.owner.subs_dropdown.set_selected.assert_not_called()
    prefs._subtitle_selected("dialog", "cancel")
    prefs.owner._subs_file_chosen.assert_called_once_with("dialog", "cancel")
    assert prefs.owner._syncing is False
    prefs.owner.subs_dropdown.set_selected.assert_called_once_with(
        preference_choices.selected_index("subs", "auto")
    )
    prefs.sync_from_owner.assert_called_once()


def test_picture_changes_are_saved_per_film_and_reset_clears_only_that_film():
    UI = extracted_preferences("_picture_changed", "_reset_picture")
    prefs = UI()
    prefs._syncing = False
    prefs._refresh_picture_preview = mock.Mock()
    prefs.sync_from_owner = mock.Mock()
    prefs.owner = SimpleNamespace(
        media=SimpleNamespace(path=Path("/films/a.mkv")),
        cfg={**picture_adjustments.DEFAULTS, "picture_by_file": {}},
    )
    save = UI._picture_changed.__globals__["save_config"]
    prefs._picture_changed(
        "picture_brightness", SimpleNamespace(get_value=lambda: 0.3))
    assert prefs.owner.cfg["picture_brightness"] == 0.0
    assert prefs.owner.cfg["picture_by_file"] == {
        "/films/a.mkv": {**picture_adjustments.DEFAULTS, "picture_brightness": 0.3},
    }
    save.assert_called_once_with(prefs.owner.cfg)

    save.reset_mock()
    prefs._refresh_picture_preview.reset_mock()
    prefs._reset_picture(None)
    assert prefs.owner.cfg["picture_by_file"] == {}
    assert prefs.owner.cfg["picture_brightness"] == 0.0
    prefs.sync_from_owner.assert_called_once_with()
    prefs._refresh_picture_preview.assert_called_once_with()
    save.assert_called_once_with(prefs.owner.cfg)


def test_picture_changes_without_a_film_update_the_global_defaults():
    UI = extracted_preferences("_picture_changed")
    prefs = UI()
    prefs._syncing = False
    prefs._refresh_picture_preview = mock.Mock()
    prefs.owner = SimpleNamespace(
        media=None, cfg={**picture_adjustments.DEFAULTS})
    prefs._picture_changed(
        "picture_contrast", SimpleNamespace(get_value=lambda: 1.2))
    assert prefs.owner.cfg["picture_contrast"] == 1.2
    assert "picture_by_file" not in prefs.owner.cfg
