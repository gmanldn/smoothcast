"""Web and GTK share one corner-radius scale (#708)."""
from __future__ import annotations

import re

import portal
import ui_theme
import ui_tokens


def test_gtk_radii_all_on_scale():
    found = {int(n) for n in re.findall(rb"border-radius:\s*(\d+)px", ui_theme.CSS)}
    assert found <= set(ui_tokens.RADIUS.values()) | {0}


def test_web_root_declares_the_same_scale():
    for name in ("sm", "md", "lg"):
        assert f"--sc-radius-{name}:{ui_tokens.RADIUS[name]}px" in portal._HTML
    for name, value in ui_tokens.SPACING.items():
        assert f"--sc-space-{name}:{value}px" in portal._HTML
    for name, value in ui_tokens.TYPE.items():
        assert f"--sc-type-{name}:{value}" in portal._HTML


def test_gtk_and_web_consume_shared_component_tokens():
    css = ui_theme.CSS.decode() if isinstance(ui_theme.CSS, bytes) else ui_theme.CSS
    assert f".card {{\n    padding: {ui_tokens.SPACING['xl']}px;\n    border-radius: {ui_tokens.RADIUS['md']}px;" in css
    assert f"font-size: {ui_tokens.TYPE['hero'].replace('rem', 'em')};" in css
    assert "--font:var(--sc-font-family)" in portal._HTML
    assert "font-size:var(--sc-type-hero)" in portal._HTML


def test_snap():
    assert ui_tokens.snap(99) == 999 and ui_tokens.snap(0) == 0
    assert ui_tokens.snap(8) == 10 and ui_tokens.snap(16) == 14


def test_gtk_spacing_all_on_scale():
    allowed = set(ui_tokens.SPACING.values()) | {0, 1, 2}
    for decl in re.findall(rb"(?:padding|margin)(?:-[a-z]+)?:\s*([^;{}]+)", ui_theme.CSS):
        assert {int(n) for n in re.findall(rb"(\d+)px", decl)} <= allowed, decl


def test_snap_space():
    assert ui_tokens.snap_space(0) == 0 and ui_tokens.snap_space(2) == 2
    assert ui_tokens.snap_space(18) == 16 and ui_tokens.snap_space(5) == 4 and ui_tokens.snap_space(10) == 8
    assert ui_tokens.snap_gtk_spacing(b".a { padding: 6px 14px; margin-top: 2px; }") == \
        b".a { padding: 4px 12px; margin-top: 2px; }"
