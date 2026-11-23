"""Guest-first portal UI semantics; pure source checks, no GUI or receiver."""
from __future__ import annotations

from html.parser import HTMLParser

import portal


class RoomHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.ids = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.elements.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#"):
            self.anchors.append(a["href"][1:])


def room_html():
    parser = RoomHTML()
    parser.feed(portal._HTML)
    return parser


def test_guest_navigation_has_unique_ids_and_real_targets():
    page = room_html()
    assert len(page.ids) == len(set(page.ids)), "Duplicate IDs break DOM event binding"
    assert set(page.anchors) <= set(page.ids)
    assert {"playback", "findPanel", "uploadCard", "queuePanel", "peoplePanel",
            "advancedPanel"} <= set(page.anchors)


def test_join_explains_shared_controls_and_optional_house_pin():
    page = room_html()
    text = portal._HTML
    assert 'id="joinTitle">Join the room' in text
    assert "only if the host has enabled one" in text
    assert "Everyone who joins can control playback" in text
    assert "No app, account or cloud" in text
    fields = {a["id"]: a for tag, a in page.elements if tag == "input" and "id" in a}
    assert fields["name"]["aria-describedby"] == "nameHint"
    assert fields["pin"]["aria-describedby"] == "pinHint"
    assert fields["pin"]["pattern"] == "[0-9]{6}"


def test_room_actions_have_touch_help_and_keep_existing_js_contract():
    page = room_html()
    text = portal._HTML
    assert text.count('class="help"') >= 6
    assert text.count("<summary>") >= 5
    assert "audio always goes into Up Next" in text.lower()
    assert "without stopping the currently playing item" in text
    assert 'id="uploadQueue" type="checkbox" checked' in text
    assert 'id="seek" type="range"' in text
    assert 'id="volume" type="range"' in text
    assert 'button.title=labels[i]' in text
    actions = {a["data-action"] for tag, a in page.elements if "data-action" in a}
    assert {"play_pause", "stop", "previous", "next"} == actions
    for required in ("people", "peers", "networkActivityRows", "activity", "findChips",
                     "findResults", "queue", "uploadButton", "cancelUpload",
                     "shortcutsHelp", "musicAutogain", "lockControls", "keepScreenOn"):
        assert required in page.ids
    assert 'function applyStatus(d)' in text
    assert 'function expireSession()' in text


def test_advanced_controls_use_native_progressive_disclosure():
    page = room_html()
    assert ("details", {"id": "advancedPanel"}) in [
        (tag, {k: v for k, v in attrs.items() if k == "id"})
        for tag, attrs in page.elements if tag == "details" and attrs.get("id") == "advancedPanel"
    ]
    text = portal._HTML
    assert "@media(min-width:820px)" in text
    assert "@media(max-width:560px)" in text
    assert "[hidden]{display:none!important}" in text
    assert "position:sticky" in text
    assert "prefers-reduced-motion:reduce" in text


def test_portal_stays_local_and_unprivileged():
    page = room_html()
    assert not any(tag == "script" and "src" in attrs for tag, attrs in page.elements)
    assert not any(tag == "link" and attrs.get("rel") in ("stylesheet", "preload")
                   for tag, attrs in page.elements)
    assert 'post("/api/login"' in portal._HTML
    assert 'credentials:"same-origin"' in portal._HTML
    assert '"X-CSRF-Token":csrf' in portal._HTML
