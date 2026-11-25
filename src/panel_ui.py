#!/usr/bin/env python3
"""Window frame: header bar, player beside a tabbed side panel, responsive reflow.

The player (now playing, transport, receiver, actions) is always the main
thing. Everything else lives in one tabbed side panel:

* **Queue**    - what plays next, search, music import
* **Devices**  - receiver status, manual IP, connection check, network activity
* **Room**     - the phone-friendly shared room (address, QR code, PIN, guests)
* **Settings** - quality, sound, subtitles
* **Info**     - stream diagnostics, audio signal, activity log

Wide windows show the panel beside the player; narrower ones stack it under the
player inside one page scroller. Keep this module free of playback logic.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango

import demo_mode
import idle_chrome
import responsive_layout
import smoothcast_assets
import text_fit
import version
from cast_widgets import APP_NAME

# (key, title, icon). Alt+<position> jumps to a tab.
PANEL_TABS: tuple[tuple[str, str, str], ...] = (
    ("queue", "Queue", "view-list-symbolic"),
    ("devices", "Devices", "video-display-symbolic"),
    ("room", "Room", "network-workgroup-symbolic"),
    ("settings", "Settings", "preferences-system-symbolic"),
    ("info", "Info", "dialog-information-symbolic"),
)


# Gap between transport buttons on one row; wrapped rows pack a little tighter.
PLAYER_MAX_WIDTH = 1000
TRANSPORT_GAP = 8
TRANSPORT_GAP_WRAPPED = 4


class PanelMixin:
    def _build_ui(self) -> None:
        # Keep the *running* release in the prominent title, not an easily
        # truncated device/status subtitle or a live on-disk git lookup.
        self.set_title(f"{APP_NAME} {version.label()}")
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(
            title=f"{APP_NAME} {version.label()}",
            subtitle=self.cfg["device"] or "No receiver selected",
        )
        self.title_widget.set_tooltip_text(f"Running {APP_NAME} {version.running_label()}")
        header.set_title_widget(self.title_widget)
        _icon_path = smoothcast_assets.icon_path()
        if _icon_path.exists():
            icon = Gtk.Image.new_from_file(str(_icon_path))
        else:
            icon = Gtk.Image.new_from_icon_name(smoothcast_assets.ICON_NAME)
        icon.set_pixel_size(22)
        header.pack_start(icon)
        identity_badge = Gtk.Label(label=version.identity_label())
        identity_badge.add_css_class("dim-label")
        identity_badge.add_css_class("caption")
        identity_badge.set_ellipsize(Pango.EllipsizeMode.END)
        identity_badge.set_max_width_chars(48)
        identity_badge.set_tooltip_text(version.identity_label())
        identity_badge.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Running {APP_NAME} {version.identity_label()}"],
        )
        header.pack_start(identity_badge)
        self.version_badge = identity_badge
        if demo_mode.active():
            # Unmistakable in screenshots: nothing here controls a real receiver (#454).
            badge = Gtk.Label(label="DEMO")
            badge.add_css_class("warning")
            badge.add_css_class("caption-heading")
            badge.set_tooltip_text("Demo mode: a fake receiver on this computer; no real devices are used")
            badge.update_property([Gtk.AccessibleProperty.LABEL],
                                  ["Demo mode, no real receivers are used"])
            header.pack_start(badge)
            self.set_title(f"{APP_NAME} {version.label()} — DEMO")
        self.demo_badge_shown = demo_mode.active()
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(self._build_menu())
        header.pack_end(menu_button)
        self.menu_button = menu_button

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        # The join link must be visible even when the Room tab is closed.
        self.room_join_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.room_join_strip.add_css_class("card")
        self.room_join_strip.set_margin_start(8)
        self.room_join_strip.set_margin_end(8)
        self.room_join_strip.set_margin_top(4)
        self.room_join_strip.set_margin_bottom(4)
        join_title = Gtk.Label(label="JOIN ROOM", xalign=0.0)
        join_title.add_css_class("heading")
        self.room_join_strip.append(join_title)
        self.room_join_label = Gtk.Label(
            label="Starting shared room…", xalign=0.0, selectable=True,
            ellipsize=Pango.EllipsizeMode.MIDDLE,
        )
        self.room_join_label.set_hexpand(True)
        self.room_join_label.add_css_class("mono")
        self.room_join_label.set_tooltip_text("Waiting for a room address")
        self.room_join_strip.append(self.room_join_label)
        self.room_join_copy_button = Gtk.Button(label="Copy join link", sensitive=False)
        self.room_join_copy_button.connect("clicked", self._copy_portal_link)
        self.room_join_copy_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Copy shared room join link"]
        )
        self.room_join_strip.append(self.room_join_copy_button)
        toolbar.add_top_bar(self.room_join_strip)
        # One full-height vertical scroller: neither column can disappear below
        # the screen when its natural height exceeds the available allocation.
        # Change this box's orientation at a breakpoint rather than forcing a
        # 1400 px-wide Gtk.Paned that clips on laptop screens.
        self.page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.page.set_vexpand(False)
        self.page.set_valign(Gtk.Align.START)
        self.left_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.left_column.set_hexpand(True)
        self.left_column.set_valign(Gtk.Align.START)
        self.player_card = self._build_now_playing()
        # Very wide windows keep the player a readable width instead of
        # stretching the seek bar and buttons across the whole screen.
        player_clamp = Adw.Clamp()
        player_clamp.set_maximum_size(PLAYER_MAX_WIDTH)
        player_clamp.set_tightening_threshold(PLAYER_MAX_WIDTH)
        player_clamp.set_child(self.player_card)
        self.left_column.append(player_clamp)
        # Build the device card before the queue: _build_queue() calls
        # _rebuild_queue() -> _refresh_controls(), which needs the receiver
        # controls. Cards are built in dependency order, then placed in tabs.
        self.right_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.right_column.set_valign(Gtk.Align.START)
        devices = [self._build_device_card(), self._build_network_activity_card()]
        room = [self._build_portal_card()]
        settings = [self._build_settings_card()]
        console = self._build_console_card()
        details = self._build_details_card()
        queue = self._build_queue()
        levels = self._build_live_levels()
        self.right_column.append(self._build_side_panel({
            "queue": [queue],
            "devices": devices,
            "room": room,
            "settings": settings,
            "info": [details, levels, console],
        }))
        self.page.append(self.left_column)
        self.page.append(self.right_column)
        self.page_scroller = Gtk.ScrolledWindow()
        self.page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.page_scroller.set_propagate_natural_width(False)
        self.page_scroller.set_propagate_natural_height(False)
        self.page_scroller.set_hexpand(True)
        self.page_scroller.set_vexpand(True)
        self.page_scroller.set_child(self.page)
        # Give the page its natural height when that exceeds the viewport (the
        # default is the *minimum*, which squeezes the stacked side panel).
        self.page_scroller.get_child().set_vscroll_policy(Gtk.ScrollablePolicy.NATURAL)
        toolbar.set_content(self.page_scroller)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)
        self.header = header
        self._idle_chrome = idle_chrome.IdleChrome(self, header)


    def _set_room_join_link(self, url: str | None, status: str = "Room unavailable") -> None:
        """Present only the active listener URL, never a cached/stale address."""
        self.room_join_label.set_text(url if url else status)
        self.room_join_label.set_tooltip_text(url if url else status)
        self.room_join_copy_button.set_sensitive(bool(url))


    # ----- side panel ---------------------------------------------------------

    def _build_side_panel(self, pages: dict[str, list[Gtk.Widget]]) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("side-panel")
        panel.set_vexpand(True)
        self.side_panel = panel

        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        strip.set_homogeneous(True)
        strip.add_css_class("panel-tabs")
        self.panel_tabs: dict[str, tuple[Gtk.ToggleButton, Gtk.Label, Gtk.Label]] = {}
        self.panel_stack = Gtk.Stack()
        self.panel_stack.set_hhomogeneous(False)
        self.panel_stack.set_vhomogeneous(False)
        self.panel_stack.set_vexpand(True)
        self.panel_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.panel_stack.set_transition_duration(120)
        self.panel_scrollers: list[Gtk.ScrolledWindow] = []

        first: Gtk.ToggleButton | None = None
        for position, (key, title, icon_name) in enumerate(PANEL_TABS, start=1):
            button = Gtk.ToggleButton()
            button.add_css_class("flat")
            button.add_css_class("panel-tab")
            button.set_hexpand(True)
            button.set_tooltip_text(f"{title} (Alt+{position})")
            button.update_property([Gtk.AccessibleProperty.LABEL], [f"{title} panel"])
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            icon_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
            icon_row.set_halign(Gtk.Align.CENTER)
            icon_row.append(Gtk.Image.new_from_icon_name(icon_name))
            badge = Gtk.Label()
            badge.add_css_class("tab-badge")
            if key == "devices":
                badge.add_css_class("attention")
            badge.set_valign(Gtk.Align.CENTER)
            badge.set_visible(False)
            icon_row.append(badge)
            caption = Gtk.Label(label=title, ellipsize=Pango.EllipsizeMode.END)
            caption.add_css_class("caption")
            box.append(icon_row)
            box.append(caption)
            button.set_child(box)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._on_panel_tab_toggled, key)
            strip.append(button)
            self.panel_tabs[key] = (button, badge, caption)

            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for widget in pages[key]:
                page.append(widget)
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_child(page)
            scroller.set_vexpand(True)
            self.panel_scrollers.append(scroller)
            self.panel_stack.add_named(scroller, key)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("panel-sep")
        panel.append(strip)
        panel.append(separator)
        panel.append(self.panel_stack)
        assert first is not None
        first.set_active(True)
        return panel


    def _on_panel_tab_toggled(self, button, key: str) -> None:
        if button.get_active():
            self.panel_stack.set_visible_child_name(key)


    def _show_panel_tab(self, key: str) -> None:
        """Bring a side-panel tab to the front (also a keyboard shortcut target)."""
        entry = self.panel_tabs.get(key)
        if entry is not None:
            entry[0].set_active(True)


    def _show_panel_tab_number(self, position: int) -> None:
        if 1 <= position <= len(PANEL_TABS):
            self._show_panel_tab(PANEL_TABS[position - 1][0])


    def _update_panel_badges(self) -> None:
        """Queue length and a 'needs a receiver' dot, without polling anything."""
        tabs = getattr(self, "panel_tabs", None)
        if not tabs:
            return
        queue_badge = tabs["queue"][1]
        count = len(self.queue)
        queue_badge.set_text(str(count) if count < 100 else "99+")
        queue_badge.set_visible(count > 0)
        devices_badge = tabs["devices"][1]
        needs_receiver = not self._device() or self.device_state == "OFFLINE"
        devices_badge.set_text("!")
        devices_badge.set_visible(needs_receiver)
        devices_badge.set_tooltip_text(
            "Choose a receiver" if not self._device() else "The receiver is offline"
        )


    # ----- responsive reflow --------------------------------------------------

    def _transport_row_width(self) -> int:
        """Minimum width of the transport controls laid out on a single row."""
        controls = self.transport_controls
        total = sum(control.measure(Gtk.Orientation.HORIZONTAL, -1)[0] for control in controls)
        return total + TRANSPORT_GAP * (len(controls) - 1)


    def _player_fixed_height(self) -> int:
        """Natural height of the player card without its (resizable) preview."""
        card = self.player_card
        # Never measure below the card's own minimum width (GTK warns about it
        # during the transient frame between a resize and the reflow).
        width = max(card.get_width(), card.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
        natural = card.measure(Gtk.Orientation.VERTICAL, width)[1]
        state = self._layout_state
        preview = state.preview_height if state is not None else self.preview.get_size_request()[1]
        return max(0, natural - max(0, preview))


    def _refresh_responsive_layout(self) -> bool:
        """Reflow once per actual size/mode change; never do I/O during resize."""
        width = self.get_width() or self._startup_width
        height = self.get_height() or self._startup_height
        self._remember_normal_geometry()
        state = responsive_layout.layout_for_size(
            width, height, self.cfg.get("density"),
            transport_min=self._transport_row_width(),
            player_fixed=self._player_fixed_height(),
        )
        if width < text_fit.NARROW_WIDTH:
            text_fit.fit_labels(self)  # long text wraps/ellipsizes instead of widening the window (#136)
        if state == self._layout_state:
            return True
        self._layout_state = state

        wide = not state.stacked
        self.page.set_orientation(
            Gtk.Orientation.VERTICAL if state.stacked else Gtk.Orientation.HORIZONTAL
        )
        self.page.set_spacing(state.spacing)
        for side in (self.page, self.left_column, self.right_column):
            side.set_margin_start(state.margin if side is self.page else 0)
            side.set_margin_end(state.margin if side is self.page else 0)
        self.page.set_margin_top(state.margin)
        self.page.set_margin_bottom(state.margin)
        self.left_column.set_spacing(state.spacing)
        self.right_column.set_spacing(state.spacing)
        # Wide: the page fills the viewport so the side panel gets the full
        # height and scrolls internally. Stacked: everything is natural height
        # and the single page scroller does the scrolling.
        self.page.set_valign(Gtk.Align.FILL if wide else Gtk.Align.START)
        self.page.set_vexpand(wide)
        self.right_column.set_hexpand(state.stacked)
        self.right_column.set_vexpand(wide)
        self.right_column.set_valign(Gtk.Align.FILL if wide else Gtk.Align.START)
        self.right_column.set_size_request(state.panel_width if wide else -1, -1)
        self.side_panel.set_vexpand(wide)
        self.panel_stack.set_vexpand(wide)
        for scroller in self.panel_scrollers:
            scroller.set_propagate_natural_height(not wide)
        self.queue_scroller.set_propagate_natural_height(not wide)
        self.queue_scroller.set_vexpand(wide)
        self.queue_scroller.set_min_content_height(140)
        self.queue_scroller.set_max_content_height(-1 if wide else 360)
        for _key, (_button, _badge, caption) in self.panel_tabs.items():
            caption.set_visible(not state.tabs_icon_only)

        if state.compact:
            self.add_css_class("compact")
        else:
            self.remove_css_class("compact")
        self.preview.set_size_request(-1, state.preview_height)
        self.preview.set_vexpand(False)
        self.meter.set_size_request(-1, 120 if state.compact else 144)
        self.play_image.set_pixel_size(24 if state.compact else 30)

        # Gtk.Grid.detach/attach preserves the actual buttons, callbacks and
        # accessibility labels while moving them between one and two rows.
        # Wrapped: prev/-10/PLAY/+10/next on the first row, with start/-30/+30/
        # stop mirrored underneath so the play button stays centred.
        self.transport_grid.set_column_spacing(
            TRANSPORT_GAP_WRAPPED if state.transport_wrapped else TRANSPORT_GAP)
        for child in self.transport_controls:
            self.transport_grid.remove(child)
        if state.transport_wrapped:
            positions = ((0, 1), (0, 0), (1, 1), (1, 0), (2, 0),
                         (3, 0), (3, 1), (4, 0), (4, 1))
        else:
            positions = tuple((n, 0) for n in range(len(self.transport_controls)))
        for button, (column, row) in zip(self.transport_controls, positions):
            self.transport_grid.attach(button, column, row, 1, 1)

        # The action strip is a FlowBox so it can never force the window wider.
        self.action_grid.set_max_children_per_line(state.action_columns)
        self.action_grid.set_min_children_per_line(min(2, state.action_columns))
        return True
