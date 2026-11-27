"""The web room and the GTK app expose the same sections (#709)."""
from __future__ import annotations

from pathlib import Path

import portal
import room_layout

SRC = Path(__file__).resolve().parents[1] / "src"


def test_every_section_exists_on_the_web():
    for section in room_layout.FRONT_PAGE + room_layout.DISCLOSED:
        assert f'id="{section.web_id}"' in portal._HTML, section.key


def test_every_section_has_a_gtk_builder():
    source = "".join(p.read_text() for p in SRC.glob("cast_*.py"))
    for section in room_layout.FRONT_PAGE + room_layout.DISCLOSED:
        assert f"def {section.gtk_builder}(" in source, section.key


def test_keys_unique_and_front_page_is_glanceable():
    assert len(set(room_layout.keys())) == len(room_layout.keys())
    assert len(room_layout.FRONT_PAGE) <= 5
