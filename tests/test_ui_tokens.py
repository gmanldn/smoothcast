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
