"""Browser/desktop parity ratchet (#635).

Fails when a row of docs/WEB_DESKTOP_PARITY.md names a desktop marker or a
browser control that no longer exists, or when a gap/partial row loses its
tracking reference, so the parity table cannot silently drift.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "WEB_DESKTOP_PARITY.md"
PORTAL = ROOT / "src" / "portal.py"
REQUIRED_AREAS = {
    "Tracks and subtitles",
    "Timing and seek",
    "Picture and video adjustments",
    "Audio tracks, delay and volume",
    "Queue / Up Next",
    "Local preview",
    "Host settings and display name",
}
STATES = ("present", "partial", "gap")


def _rows() -> list[list[str]]:
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("Area", ""):
            continue
        if set(cells[0]) <= {"-", ":", " "}:
            continue
        rows.append(cells)
    return rows


def test_the_matrix_covers_every_area_and_state():
    rows = _rows()
    assert rows, "the parity matrix is empty"
    areas = {row[0] for row in rows}
    assert REQUIRED_AREAS <= areas, sorted(REQUIRED_AREAS - areas)
    for area, _desktop, _browser, state in rows:
        assert state.split()[0] in STATES, (area, state)


def test_desktop_markers_still_exist():
    for area, desktop, _browser, _state in _rows():
        path, _, marker = desktop.partition("::")
        marker = marker.strip("`")
        source = ROOT / path.strip("`")
        assert source.is_file(), (area, path)
        if marker:
            assert marker in source.read_text(encoding="utf-8"), (area, marker)


def test_browser_controls_still_exist_and_gaps_are_referenced():
    portal = PORTAL.read_text(encoding="utf-8")
    for area, _desktop, browser, state in _rows():
        controls = re.findall(r"`#([a-zA-Z][\w-]*)`", browser)
        if state.startswith(("present", "partial")):
            assert controls, (area, "a present/partial row needs a browser control")
            for control in controls:
                assert f'id="{control}"' in portal, (area, control)
        if state.startswith(("gap", "partial")):
            assert re.search(r"#\d+", state), (area, state)
