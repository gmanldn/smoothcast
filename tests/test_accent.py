"""Accent colour presets (issue #135): WCAG contrast maths, bounded presets, safe CSS, config."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import accent
import config_control
import preference_choices


def test_contrast_maths_matches_the_wcag_reference_values():
    assert accent.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert accent.contrast_ratio("#79baff", "#79baff") == pytest.approx(1.0)
    assert accent.contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.02)   # the classic AA edge
    assert accent.contrast_ratio("#ffffff", "#000000") == accent.contrast_ratio("#000000", "#ffffff")
    assert accent.relative_luminance("#ffffff") == pytest.approx(1.0)
    assert accent.relative_luminance("#000000") == 0.0


@pytest.mark.parametrize("bad", ["", "red", "#fff", "#12345g", "123456", "#1234567", None, 5])
def test_malformed_colours_are_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        accent.relative_luminance(bad)


def test_mix_blends_and_clamps():
    assert accent.mix("#000000", "#ffffff", 0.5) == "#808080"
    assert accent.mix("#102030", "#ffffff", 0) == "#102030"
    assert accent.mix("#102030", "#ffffff", 5) == "#ffffff"
    assert accent.mix("#102030", "#ffffff", -5) == "#102030"


def test_text_on_picks_whichever_text_has_more_contrast():
    assert accent.text_on("#ffc857") == accent.DARK_TEXT
    assert accent.text_on("#10203a") == accent.LIGHT_TEXT
    for background in ("#000000", "#ffffff", "#808080", "#79baff", "#3a3a8c"):
        text = accent.text_on(background)
        other = accent.LIGHT_TEXT if text == accent.DARK_TEXT else accent.DARK_TEXT
        assert accent.contrast_ratio(background, text) >= accent.contrast_ratio(background, other)


# --- presets ---------------------------------------------------------------------

def test_presets_are_bounded_unique_and_start_with_the_default():
    ids = [pid for pid, _label, _hex in accent.PRESETS]
    labels = [label for _pid, label, _hex in accent.PRESETS]
    assert ids[0] == accent.DEFAULT_ID and 3 <= len(ids) <= 12
    assert len(set(ids)) == len(ids) and len(set(labels)) == len(labels)
    assert accent.IDS == frozenset(ids)


@pytest.mark.parametrize("preset_id,label,colour", accent.PRESETS)
def test_every_preset_is_accessible(preset_id, label, colour):
    hover = accent.mix(colour, accent.LIGHT_TEXT, 0.18)
    text = accent.text_on(colour)
    assert accent.contrast_ratio(colour, text) >= 4.5, "button text on the accent (WCAG AA)"
    assert accent.contrast_ratio(hover, text) >= 4.5, "button text on the hover shade"
    for surface in accent.SURFACES:
        assert accent.contrast_ratio(colour, surface) >= 3.0, f"accent against {surface} (WCAG non-text)"


@pytest.mark.parametrize("junk", [None, 5, "", "nope", "TEAL", " teal", ["teal"], "<script>", "teal; x: y"])
def test_unknown_values_fall_back_to_the_default(junk):
    assert accent.normalize(junk) == accent.DEFAULT_ID
    assert accent.css_for(junk) == ""


def test_default_adds_no_override_and_others_override_every_accent_rule():
    assert accent.css_for("default") == ""
    css = accent.css_for("amber")
    colour = accent.accent_hex("amber")
    for selector in ("button.suggested-action", "button.big-play", "scale highlight", "scale slider",
                     "switch:checked", ".queue-row.current .queue-title"):
        assert selector in css
    assert colour in css and accent.text_on(colour) in css
    assert css.count("{") == css.count("}")


def test_generated_css_contains_only_colour_rules():
    for preset_id, _label, _hex in accent.PRESETS:
        css = accent.css_for(preset_id)
        assert not re.search(r"url\(|@import|expression|javascript|;\s*;", css, re.I)
        declared = set(re.findall(r"^\s+([a-z-]+):", css, re.M))
        assert declared <= {"color", "background-color", "border-color"}


# --- config and choices ----------------------------------------------------------------

def test_config_loader_accepts_only_known_presets():
    defaults = {"accent": "default"}
    assert config_control.sanitise_config({"accent": "violet"}, defaults)["accent"] == "violet"
    for bad in ("neon", "", None, 3, ["teal"], "#ff0000"):
        assert config_control.sanitise_config({"accent": bad}, defaults)["accent"] == "default"


def test_preference_choices_mirror_the_presets():
    assert [v for _l, v in preference_choices.OPTIONS["accent"]] == [p for p, _l, _h in accent.PRESETS]
    assert preference_choices.labels("accent")[0] == "Default blue"
    assert preference_choices.selected_index("accent", "teal") == 1
    assert preference_choices.selected_index("accent", "unknown") == 0
    assert preference_choices.selected_value("accent", 3) == accent.PRESETS[3][0]


def test_wiring_layers_a_second_provider_and_never_touches_the_gtk_theme():
    control = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert "STYLE_PROVIDER_PRIORITY_APPLICATION + 1" in control and "remove_provider_for_display" in control
    assert "apply_accent(load_config().get(\"accent\"))" in control
    assert "gtk-theme-name" not in control and "Settings.get_default" not in control
    prefs = (ROOT / "src" / "preferences_ui.py").read_text(encoding="utf-8")
    assert 'key == "accent"' in prefs and "apply_accent(value)" in prefs
    assert '"accent": "default"' in (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    assert '"accent"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
