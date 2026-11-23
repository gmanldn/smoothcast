"""Cross-surface accent presets stay canonical, accessible, and GTK-free (#525)."""
from __future__ import annotations

from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import accent
import design_tokens
import portal


def test_every_preset_has_light_and_dark_accessible_variants():
    palettes = design_tokens.web_accents()
    assert set(palettes) == accent.IDS
    for preset, variants in palettes.items():
        assert set(variants) == set(design_tokens.SCHEMES)
        for scheme, colours in variants.items():
            assert set(colours) == {"accent", "on_accent"}
            assert all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in colours.values())
            assert design_tokens.contrast_ratio(colours["accent"], design_tokens.SCHEMES[scheme]["card"]) >= 3.0, (preset, scheme)
            assert design_tokens.contrast_ratio(colours["on_accent"], colours["accent"]) >= 4.5, (preset, scheme)


def test_dark_preset_colours_match_existing_gtk_user_choices():
    palettes = design_tokens.web_accents()
    assert palettes["default"]["dark"] == {
        "accent": design_tokens.DARK["accent"], "on_accent": design_tokens.DARK["on_accent"]}
    for preset in accent.IDS - {"default"}:
        assert palettes[preset]["dark"]["accent"] == accent.accent_hex(preset)
        assert palettes[preset]["dark"]["on_accent"] == accent.text_on(accent.accent_hex(preset))


def test_room_page_includes_only_server_checked_color_presets():
    html = portal._page().decode("utf-8")
    assert "__SC_ACCENTS__" not in html
    assert "function applyAccentPreset(value)" in html
    assert 'Object.hasOwn(ROOM_ACCENTS,value)?value:"default"' in html
    assert 'applyAccentPreset(s.accent)' in html
    start = html.index("const ROOM_ACCENTS=") + len("const ROOM_ACCENTS=")
    decoded = json.loads(html[start:html.index(";", start)])
    assert decoded == design_tokens.web_accents()
    for scheme in ("dark", "light"):
        assert f"--sc-user-accent-{scheme}" in html
        assert f"--sc-user-on-accent-{scheme}" in html
    assert "var(--sc-user-accent-dark, " in html
    assert "var(--sc-user-accent-light, " in html


def test_gtk_keeps_native_adwaita_color_semantics():
    import ui_theme
    css = ui_theme.CSS.decode("utf-8")
    assert "@accent_bg_color" in css and "@accent_fg_color" in css
    assert "@card_bg_color" in css and "@card_fg_color" in css
    assert "@error_color" in css and "@warning_color" in css
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
