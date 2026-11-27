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
        assert f"--r-{name}:{ui_tokens.RADIUS[name]}px" in portal._HTML


def test_snap():
    assert ui_tokens.snap(99) == 999 and ui_tokens.snap(0) == 0
    assert ui_tokens.snap(8) == 10 and ui_tokens.snap(16) == 14
