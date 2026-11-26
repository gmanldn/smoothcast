"""Browser casting entry is honest, accessible navigation; no GUI or receiver."""
from __future__ import annotations

from html.parser import HTMLParser
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a":
            self.links.append(a)


def _page():
    parser = _Anchors()
    # Check the final served document: Screens and Mesh panels are inserted by _page().
    parser.feed(portal._page().decode("utf-8"))
    return parser


def test_cast_entry_links_to_real_find_and_upload_controls():
    page = _page()
    assert {"homePanel", "homeUpload", "homeFind", "findPanel", "uploadCard"} <= page.ids
    assert any(a.get("href") == "#uploadCard" for a in page.links)
    assert any(a.get("href") == "#findPanel" for a in page.links)
    assert any(a.get("href") == "#homePanel" for a in page.links)
    assert all(a["href"][1:] in page.ids for a in page.links
               if a.get("href", "").startswith("#"))


def test_entry_is_keyboard_accessible_without_custom_js():
    html = portal._HTML
    assert 'id="homeUpload" href="#uploadCard"' in html
    assert 'id="homeFind" href="#findPanel"' in html
    assert 'id="homePanel" aria-labelledby="homeHeading"' in html


def test_no_native_chrome_cast_menu_claim():
    html = portal._HTML
    entry = html.split('<details id="castEntry"', 1)[1].split("</details>", 1)[0]
    assert "Chrome" in entry and "not yet supported" in entry
    # Plain wording (#599): say Chrome's own Cast button is not supported, never claim it.
    assert "own Cast button is not yet supported" in entry
    assert "Cast via SmoothCast Mesh" not in entry


def test_entry_never_uploads_or_casts_on_navigation():
    entry = portal._HTML.split('<details id="castEntry"', 1)[1].split("</details>", 1)[0]
    assert "<button" not in entry and "<script" not in entry
    assert "onclick" not in entry and "onchange" not in entry
    assert "/api/" not in entry


def test_existing_upload_and_cast_flow_untouched():
    html = portal._HTML
    assert 'id="uploadCard"' in html
    assert 'id="uploadQueue" type="checkbox" checked' in html
    assert 'id="uploadButton"' in html
    assert "cast_upload" in html or "/api/upload" in html
