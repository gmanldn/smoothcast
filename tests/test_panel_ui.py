"""GTK-free checks for the player + tabbed side-panel layout (src/panel_ui.py).

The module imports GTK, so these read it as source/AST. Behaviour (tab
switching, minimum widths, the Cast button staying on screen) is exercised in a
private Xvfb session by ``scripts/gui_checks.py side-panel``.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

from gui_source import combined_source

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "src" / "panel_ui.py").read_text(encoding="utf-8")


def tabs() -> tuple[tuple[str, str, str], ...]:
    for node in ast.parse(PANEL).body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PANEL_TABS":
            return ast.literal_eval(node.value)
    raise AssertionError("PANEL_TABS not found")


def test_tabs_are_unique_labelled_and_icon_backed():
    keys = [key for key, _title, _icon in tabs()]
    assert keys == ["queue", "devices", "room", "settings", "info"]
    assert len({title for _key, title, _icon in tabs()}) == len(keys)
    assert all(icon.endswith("-symbolic") for _key, _title, icon in tabs())


def test_every_card_is_placed_in_exactly_one_tab():
    # A dropped builder would silently remove a feature from the window.
    for builder in ("_build_now_playing", "_build_device_card", "_build_network_activity_card",
                    "_build_portal_card", "_build_settings_card", "_build_console_card",
                    "_build_details_card", "_build_queue", "_build_live_levels"):
        assert PANEL.count(f"self.{builder}()") == 1, builder
    for key in ("queue", "devices", "room", "settings", "info"):
        assert f'"{key}": ' in PANEL


def test_tab_switching_is_keyboard_reachable_and_documented():
    source = combined_source()
    assert 'add(f"<Alt>{position}"' in source
    assert "len(PANEL_TABS) + 1" in source
    assert "Alt+1 – 5" in source  # keyboard shortcuts window
    assert 'add("<Control>f", self._focus_queue_search)' in source
    assert 'self._show_panel_tab("queue")' in source  # Ctrl+F reveals the search box


def test_tab_buttons_have_accessible_names_and_tooltips():
    assert "Gtk.AccessibleProperty.LABEL" in PANEL
    assert 'set_tooltip_text(f"{title} (Alt+{position})")' in PANEL


def test_stacked_page_gets_its_natural_height():
    # Default scrolling uses the *minimum* height, which squeezed the stacked
    # side panel to a sliver; the page must use its natural height.
    assert "set_vscroll_policy(Gtk.ScrollablePolicy.NATURAL)" in PANEL
    assert "set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)" in PANEL  # never scrolls sideways


def test_layout_inputs_are_measured_not_guessed():
    assert "transport_min=self._transport_row_width()" in PANEL
    assert "player_fixed=self._player_fixed_height()" in PANEL
    # Never measure below a widget's own minimum width (GTK warns about it).
    assert re.search(r"max\(card\.get_width\(\), card\.measure\(Gtk\.Orientation\.HORIZONTAL, -1\)\[0\]\)", PANEL)


def test_receiver_picker_sits_in_the_player_next_to_the_cast_button():
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")
    player = ui.split("def _build_now_playing", 1)[1].split("def _build_live_levels", 1)[0]
    assert "self.device_dropdown = Gtk.DropDown" in player
    assert player.index("self.device_dropdown") < player.index("self.cast_button")
    device_card = ui.split("def _build_device_card", 1)[1].split("def _build_portal_card", 1)[0]
    assert "device_dropdown" not in device_card


def test_room_join_link_is_always_visible_above_player_and_is_copyable():
    # This strip belongs to the toolbar, not the Room side-panel tab.
    assert "self.room_join_strip = Gtk.Box" in PANEL
    assert 'toolbar.add_top_bar(self.room_join_strip)' in PANEL
    assert PANEL.index('toolbar.add_top_bar(self.room_join_strip)') < PANEL.index('self.page = Gtk.Box')
    assert 'label="JOIN ROOM"' in PANEL
    assert 'label="Copy join link", sensitive=False' in PANEL
    assert 'self.room_join_copy_button.connect("clicked", self._copy_portal_link)' in PANEL
    assert "Gtk.AccessibleProperty.LABEL" in PANEL
    assert "Pango.EllipsizeMode.MIDDLE" in PANEL


def test_room_join_link_tracks_portal_start_failure_and_shutdown():
    src = (ROOT / "src" / "cast_portal.py").read_text(encoding="utf-8")
    assert 'self._set_room_join_link(self._portal.url)' in src
    assert 'self._set_room_join_link(None, "Room stopped")' in src
    assert 'self._set_room_join_link(None, "Room unavailable — connect to a private LAN")' in src
    assert 'self._set_room_join_link(None, "Room unavailable — check network settings")' in src
    assert 'self.room_join_copy_button.set_sensitive(bool(url))' in PANEL
