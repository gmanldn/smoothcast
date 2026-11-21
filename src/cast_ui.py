#!/usr/bin/env python3
"""MainWindow UI construction, theming and status text."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
import pathlib
import time

from utils import pretty_title
import cast_targets

import responsive_layout

import buffer_health
import idle_chrome
import notifications
import playback_state
import progress_model
import text_fit

import smoothcast_assets
import ui_theme

import version

from cast_widgets import (
    APP_NAME, fmt_time, save_config, SeekBar, LevelMeter, PreviewScreen, Async,
    BufferHealthGraph,
)
import network_route_ui
from bookmark_ui import BookmarkUiMixin


class UiMixin(BookmarkUiMixin):


    def present(self) -> None:
        """A launch must always end with a visible, focused window.

        GTK's own present() raises and focuses, but a minimised window stays
        minimised on some sessions, so clear that first.
        """
        self.unminimize()
        super().present()


    def _build_ui(self) -> None:
        # Keep the *running* release in the prominent title, not an easily
        # truncated device/status subtitle or a live on-disk git lookup.
        self.set_title(f"{APP_NAME} {version.label()}")
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(
            title=f"{APP_NAME} {version.label()}",
            subtitle=self.cfg["device"] or "No receiver selected",
        )
        self.title_widget.set_tooltip_text(f"Running {APP_NAME} {version.label()}")
        header.set_title_widget(self.title_widget)
        _icon_path = smoothcast_assets.icon_path()
        if _icon_path.exists():
            icon = Gtk.Image.new_from_file(str(_icon_path))
        else:
            icon = Gtk.Image.new_from_icon_name(smoothcast_assets.ICON_NAME)
        icon.set_pixel_size(22)
        header.pack_start(icon)
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(self._build_menu())
        header.pack_end(menu_button)
        self.menu_button = menu_button

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
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
        self.left_column.append(self._build_now_playing())
        # Build the device card before the queue: _build_queue() calls
        # _rebuild_queue() -> _refresh_controls(), which needs device_dropdown.
        self.right_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.right_column.set_valign(Gtk.Align.START)
        self.right_column.append(self._build_device_card())
        self.right_column.append(self._build_network_activity_card())
        self.right_column.append(self._build_portal_card())
        self.right_column.append(self._build_settings_card())
        self.right_column.append(self._build_console_card())
        self.right_column.append(self._build_details_card())
        self.left_column.append(self._build_queue())
        self.left_column.append(self._build_live_levels())
        self.page.append(self.left_column)
        self.page.append(self.right_column)
        self.page_scroller = Gtk.ScrolledWindow()
        self.page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.page_scroller.set_propagate_natural_width(False)
        self.page_scroller.set_propagate_natural_height(False)
        self.page_scroller.set_hexpand(True)
        self.page_scroller.set_vexpand(True)
        self.page_scroller.set_child(self.page)
        toolbar.set_content(self.page_scroller)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)
        self.header = header
        self._idle_chrome = idle_chrome.IdleChrome(self, header)


    def action_report_problem(self) -> None:
        """Open a prefilled GitHub bug form in the browser; nothing is sent by the app (#274)."""
        import issue_report

        try:
            Gio.AppInfo.launch_default_for_uri(issue_report.report_url(version.label()), None)
        except GLib.Error as exc:
            self.toast(f"Could not open the browser: {exc.message}", error=True)
            return
        self.toast("Opening GitHub. Attach the file from Save diagnostics… to your report.")


    def action_preferences(self) -> None:
        """Reuse one searchable preferences window, keeping the player clean."""
        from preferences_ui import PreferencesWindow

        preferences = getattr(self, "_preferences_window", None)
        if preferences is None:
            preferences = PreferencesWindow(self)
            preferences.connect("close-request", self._preferences_closed)
            self._preferences_window = preferences
        preferences.sync_from_owner()
        preferences.present()

    def _preferences_closed(self, _window) -> bool:
        self._preferences_window = None
        return False


    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Open video…", "app.open")
        section.append("Play locally", "app.play-locally")
        section.append("Add videos to queue…", "app.add-files")
        section.append("Open URL…", "app.open-url")
        recents = Gio.Menu()
        for index, path in enumerate(self.cfg["recents"][:8]):
            recents.append(pathlib.Path(path).name, f"app.recent-{index}")
        if self.cfg["recents"]:
            recents.append("Clear recent files", "app.clear-recents")
            section.append_submenu("Open recent", recents)
        favourites = Gio.Menu()
        for index, path in enumerate(self.cfg["favourites"][:16]):
            favourites.append(pathlib.Path(path).name, f"app.favourite-{index}")
        favourites.append("Pin or unpin current file", "app.favourite")
        if self.cfg["favourites"]:
            favourites.append("Clear favourites", "app.clear-favourites")
        section.append_submenu("Favourites", favourites)
        section.append_submenu("Bookmarks", self._build_bookmarks_menu())
        menu.append_section(None, section)
        playback = Gio.Menu()
        playback.append("Stop stream", "app.stop-stream")
        playback.append("Toggle fullscreen", "app.fullscreen")
        playback.append("Loop", "app.loop")
        playback.append("Pin or unpin receiver", "app.pin-receiver")
        playback.append("Clear watch history", "app.clear-history")
        playlist = Gio.Menu()
        playlist.append("Loop all", "app.loop-all")
        playlist.append("Shuffle queue", "app.shuffle-queue")
        playlist.append("Save playlist", "app.save-playlist")
        playlist.append("Load playlist", "app.load-playlist")
        playback.append("Theater mode", "app.theater")
        playlist.append("Auto-shutdown after playlist", "app.auto-shutdown")
        speed = Gio.Menu()
        for s in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            speed.append(f"{s}x", f"app.speed-{str(s).replace('.','_')}")
        speed.append("Custom…", "app.custom-speed")
        playback.append_submenu("Speed", speed)
        captions = Gio.Menu()
        captions.append("Earlier by 100 ms (G)", "app.subtitle-earlier")
        captions.append("Later by 100 ms (H)", "app.subtitle-later")
        captions.append("Reset delay", "app.subtitle-reset")
        playback.append_submenu("Subtitle delay", captions)
        lipsync = Gio.Menu()
        lipsync.append("Sound earlier by 50 ms (Shift+G)", "app.audio-earlier")
        lipsync.append("Sound later by 50 ms (Shift+H)", "app.audio-later")
        lipsync.append("Reset delay", "app.audio-reset")
        playback.append_submenu("Audio delay (lip-sync)", lipsync)
        sleep = Gio.Menu()
        for m in (0, 15, 30, 45, 60):
            sleep.append(f"{m} min" if m else "Off", f"app.sleep-{m}")
        playback.append_submenu("Sleep timer", sleep)
        playback.append("Screenshot", "app.screenshot")
        menu.append_submenu("Playback", playback)
        menu.append_submenu("Playlist", playlist)
        scheme = Gio.Menu()
        for label, value in (("Follow system", "default"), ("Light", "force-light"), ("Dark", "prefer-dark")):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value("app.color-scheme", GLib.Variant("s", value))
            scheme.append_item(item)
        scheme.append("Auto theme by time", "app.auto-theme")
        menu.append_submenu("Appearance", scheme)
        menu.append("Preferences…", "app.preferences")
        help_menu = Gio.Menu()
        help_menu.append("Benchmark playback quality…", "app.benchmark")
        help_menu.append("Keyboard shortcuts", "app.shortcuts")
        help_menu.append("Save diagnostics…", "app.save-diagnostics")
        help_menu.append("Report a problem…", "app.report-problem")
        help_menu.append("About SmoothCast", "app.about")

        menu.append_submenu("Help", help_menu)
        menu.append("Quit", "app.quit")
        return menu


    def _build_now_playing(self) -> Gtk.Box:
        card, body = self._card("Now Playing")
        card.add_css_class("hero-card")
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.np_title = Gtk.Label(label="Ready to cast", xalign=0.0, hexpand=True, ellipsize=3)
        self.np_title.add_css_class("hero-title")
        self.state_chip = Gtk.Label(label="Ready")
        self.state_chip.add_css_class("chip")
        self.state_chip.add_css_class("idle")
        title_row.append(self.np_title)
        title_row.append(self.state_chip)
        body.append(title_row)
        self.np_meta = Gtk.Label(label="Open a video and send it to your TV", xalign=0.0, wrap=True)
        self.np_meta.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.np_meta.set_max_width_chars(72)
        self.np_meta.add_css_class("dim-label")
        self.np_meta.add_css_class("hero-subtitle")
        body.append(self.np_meta)
        # Preview screen above the scrubbing bar.
        self.preview = PreviewScreen()
        self.preview_picture = Gtk.Picture()
        self.preview_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preview_picture.set_can_target(False)
        self.preview_picture.set_visible(False)
        self.preview_overlay = Gtk.Overlay()
        self.preview_overlay.set_child(self.preview)
        self.preview_overlay.add_overlay(self.preview_picture)
        # Real video/audio playback is embedded into the existing preview panel.
        self.local_video = Gtk.Video()
        self.local_video.set_autoplay(False)
        self.local_video.set_can_target(False)
        self.local_video.set_visible(False)
        self.local_video.set_hexpand(True)
        self.local_video.set_vexpand(True)
        self.preview_overlay.add_overlay(self.local_video)
        subtitle_drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        subtitle_drop.connect("drop", self._drop_subtitle)
        self.preview_overlay.add_controller(subtitle_drop)
        body.append(self.preview_overlay)
        self.seekbar = SeekBar(self.seek_to, self._on_hover)
        body.append(self.seekbar)
        clock_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.elapsed_label = Gtk.Label(label="0:00:00", xalign=0.0, hexpand=True)
        self.elapsed_label.add_css_class("caption")
        self.elapsed_label.add_css_class("mono")
        self.remaining_label = Gtk.Label(label="--:--", xalign=1.0)
        self.remaining_label.add_css_class("caption")
        self.remaining_label.add_css_class("mono")
        self.remaining_label.add_css_class("dim-label")
        clock_row.append(self.elapsed_label)
        clock_row.append(self.remaining_label)
        body.append(clock_row)

        transport = Gtk.Grid(column_spacing=8, row_spacing=8)
        transport.set_halign(Gtk.Align.CENTER)
        self.transport_grid = transport
        self.start_button = self._icon_button(
            "media-skip-backward-symbolic", "Back to start (Home)",
            "transport", self._back_to_start, size=28,
        )
        self.prev_button = self._icon_button("go-previous-symbolic", "Previous in queue (P)", "transport", self.on_prev, size=28)
        self.back30_button = self._text_button("−30", "Back 30 seconds (Shift+←)", self._skip_back30)
        self.back30_button.add_css_class("transport-step")
        self.back10_button = self._text_button("−10", "Back 10 seconds (←)", self._skip_back10)
        self.back10_button.add_css_class("transport-step")
        self.play_button = Gtk.Button()
        self.play_button.add_css_class("suggested-action")
        self.play_button.add_css_class("big-play")
        self.play_button.add_css_class("transport-primary")
        self.play_image = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        self.play_image.set_pixel_size(50)
        self.play_button.set_child(self.play_image)
        self.play_button.set_tooltip_text("Play / Pause (Space)")
        self.play_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Play or pause"]
        )
        self.play_button.connect("clicked", lambda _b: self.toggle_play())
        self.fwd10_button = self._text_button("+10", "Forward 10 seconds (→)", self._skip_forward10)
        self.fwd10_button.add_css_class("transport-step")
        self.fwd30_button = self._text_button("+30", "Forward 30 seconds (Shift+→)", self._skip_forward30)
        self.fwd30_button.add_css_class("transport-step")
        self.next_button = self._icon_button("go-next-symbolic", "Next in queue (N)", "transport", self.on_next, size=28)
        self.stop_button = self._icon_button("media-playback-stop-symbolic", "Stop (S)", "transport stop-control", self.stop_stream, size=28)
        self.transport_controls = (
            self.start_button, self.prev_button, self.back30_button,
            self.back10_button, self.play_button, self.fwd10_button,
            self.fwd30_button, self.next_button, self.stop_button,
        )
        for index, widget in enumerate(self.transport_controls):
            transport.attach(widget, index, 0, 1, 1)
        body.append(transport)

        volume_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        volume_row.add_css_class("volume-row")
        volume_title = Gtk.Label(label="Volume")
        volume_title.add_css_class("volume-label")
        volume_row.append(volume_title)
        self.mute_button = Gtk.ToggleButton()
        self.mute_button.set_icon_name("audio-volume-high-symbolic")
        self.mute_button.set_tooltip_text("Mute (M)")
        self.mute_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Mute"]
        )
        self.mute_button.add_css_class("flat")
        self.mute_button.connect("toggled", self._on_mute)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Volume"]
        )
        self.volume_scale.set_hexpand(True)
        self._syncing = True
        self.volume_scale.set_value(50)
        self._syncing = False
        self.volume_scale.connect("value-changed", self._on_volume_changed)
        self.volume_label = Gtk.Label(label="50%")
        self.volume_label.add_css_class("caption")
        self.volume_label.add_css_class("mono")
        self.volume_label.set_width_chars(4)
        volume_row.append(self.mute_button)
        volume_row.append(self.volume_scale)
        volume_row.append(self.volume_label)
        body.append(volume_row)

        action_row = Gtk.Grid(column_spacing=8, row_spacing=8)
        action_row.set_hexpand(True)
        self.action_grid = action_row
        open_button = Gtk.Button(label="Open media")
        self.open_button = open_button
        open_button.add_css_class("action-control")
        open_button.add_css_class("primary-action")
        open_button.connect("clicked", lambda _b: self.open_video())
        self.cast_button = Gtk.Button(label="Cast to TV")
        self.cast_button.add_css_class("action-control")
        self.cast_button.set_hexpand(False)
        self.cast_button.connect("clicked", lambda _b: self.cast_selected())
        self.local_button = Gtk.Button(label="Play locally")
        self.local_button.add_css_class("action-control")
        self.local_button.set_hexpand(False)
        self.local_button.set_tooltip_text("Play the selected file locally before casting")
        self.local_button.connect("clicked", lambda _b: self._play_locally())
        self.stop_tv_button = Gtk.Button(label="Stop TV")
        self.stop_tv_button.add_css_class("destructive-action")
        self.stop_tv_button.add_css_class("action-control")
        self.stop_tv_button.set_hexpand(False)
        self.stop_tv_button.set_sensitive(False)
        self.stop_tv_button.connect("clicked", lambda _b: self.stop_stream())
        self.cc_button = Gtk.ToggleButton(label="CC")
        self.cc_button.add_css_class("action-control")
        self.cc_button.set_tooltip_text("Toggle captions on the TV")
        self.cc_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Captions"]
        )
        self.cc_button.connect("toggled", self._on_cc_toggled)
        self.action_controls = (
            open_button, self.cast_button, self.local_button, self.stop_tv_button, self.cc_button,
        )
        for index, button in enumerate(self.action_controls):
            action_row.attach(button, index, 0, 1, 1)
        body.append(action_row)
        return card


    def _build_live_levels(self) -> Gtk.Box:
        card, body = self._card(
            "Audio signal", "Real-time input, processed output and headroom."
        )
        card.add_css_class("meter-card")
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        for text in ("INPUT L / R", "OUTPUT L / R", "MASTER / 0 dBFS"):
            label = Gtk.Label(label=text)
            label.add_css_class("meter-legend")
            legend.append(label)
        body.append(legend)
        self.meter = LevelMeter()
        body.append(self.meter)
        self.levels_hint = Gtk.Label(label="Meter becomes active while analysing audio.", xalign=0.0, wrap=True)
        self.levels_hint.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.levels_hint.add_css_class("caption")
        body.append(self.levels_hint)
        return card


    def _build_console_card(self) -> Gtk.Box:
        card, body = self._card(
            "Activity", "Casting, encoder and connection events."
        )
        card.add_css_class("activity-card")
        card.set_vexpand(False)
        self.console_empty = Gtk.Label(
            label="No activity yet — events appear here when you start a cast.",
            xalign=0.0, wrap=False, ellipsize=Pango.EllipsizeMode.END,
        )
        self.console_empty.add_css_class("console-idle")
        body.append(self.console_empty)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(84)
        scroller.set_max_content_height(230)
        # Only the outer page should negotiate natural vertical size.
        # Inner list contents change asynchronously and can otherwise give
        # GtkBox contradictory min/natural height requests during relayout.
        scroller.set_propagate_natural_height(False)
        self.console_scroller = scroller
        self.console_list = Gtk.ListBox()
        self.console_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.console_list.add_css_class("boxed-list")
        scroller.set_child(self.console_list)
        body.append(scroller)
        clear = Gtk.Button(label="Clear activity")
        clear.set_halign(Gtk.Align.END)
        clear.add_css_class("flat")
        clear.connect("clicked", lambda _b: self._clear_console())
        self.console_clear_button = clear
        body.append(clear)
        self._refresh_console()
        return card


    def _build_queue(self) -> Gtk.Box:
        card, body = self._card("Up next")
        card.add_css_class("queue-card")
        card.set_vexpand(False)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_button = Gtk.Button(label="Add media")
        add_button.connect("clicked", lambda _b: self.add_files())
        clear_button = self._icon_button(
            "edit-clear-all-symbolic", "Clear queue", "flat", self.clear_queue,
        )
        toolbar.append(add_button)
        toolbar.append(self._build_music_actions())
        toolbar.append(clear_button)
        toolbar.append(Gtk.Box(hexpand=True))
        auto_label = Gtk.Label(label="Auto-play")
        auto_label.add_css_class("caption")
        self.autonext_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.autonext_switch.set_active(bool(self.cfg["autonext"]))
        self.autonext_switch.connect("notify::active", self._on_autonext)
        toolbar.append(auto_label)
        toolbar.append(self.autonext_switch)
        body.append(toolbar)
        body.append(self._build_music_import_status())

        self.queue_search = Gtk.SearchEntry()
        self.queue_search.set_placeholder_text("Search filenames or folders…")
        self.queue_search.set_tooltip_text("Filter the queue without changing playback order (Ctrl+F)")
        self.queue_search.connect("search-changed", self._on_queue_search)
        body.append(self.queue_search)
        self.queue_no_matches = Gtk.Label(label="No videos match your search.", xalign=0.0)
        self.queue_no_matches.add_css_class("dim-label")
        self.queue_no_matches.set_visible(False)
        body.append(self.queue_no_matches)

        self.queue_summary = Gtk.Label(label="", xalign=0.0)
        self.queue_summary.add_css_class("caption")
        self.queue_summary.set_visible(False)
        body.append(self.queue_summary)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(100)
        scroller.set_max_content_height(270)
        # Only the outer page should negotiate natural vertical size.
        # Inner list contents change asynchronously and can otherwise give
        # GtkBox contradictory min/natural height requests during relayout.
        scroller.set_propagate_natural_height(False)
        self.queue_scroller = scroller
        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.queue_list.add_css_class("boxed-list")
        self.queue_list.connect("row-activated", self._on_queue_activated)
        self.queue_list.connect("row-selected", self._on_queue_selected)
        self.queue_list.set_filter_func(self._queue_row_matches)
        self._install_queue_drop_target(self.queue_list)
        scroller.set_child(self.queue_list)
        body.append(scroller)

        # A compact, purposeful empty state instead of a 300px vacant card.
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        empty.add_css_class("empty-state")
        empty.set_halign(Gtk.Align.FILL)
        emblem = Gtk.Image.new_from_icon_name("view-list-symbolic")
        emblem.set_pixel_size(28)
        emblem.add_css_class("empty-icon")
        emblem.set_halign(Gtk.Align.CENTER)
        empty.append(emblem)
        title = Gtk.Label(label="Queue is empty")
        title.add_css_class("empty-title")
        empty.append(title)
        subtitle = Gtk.Label(
            label="Choose Add media or Add Music to build your queue.",
            wrap=True,
        )
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class("empty-subtitle")
        empty.append(subtitle)
        self.queue_empty = empty
        body.append(empty)
        self._rebuild_queue()
        return card


    def _build_device_card(self) -> Gtk.Box:
        card, body = self._card(
            "Output device", "Google Cast or DLNA/UPnP renderer on your network."
        )
        card.add_css_class("device-card")
        row_status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        icon.set_pixel_size(20)
        row_status.append(icon)
        self.device_status_badge = Gtk.Label(label="DISCOVERING")
        self.device_status_badge.add_css_class("device-badge")
        row_status.append(self.device_status_badge)
        row_status.append(Gtk.Box(hexpand=True))
        body.append(row_status)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.device_dropdown = Gtk.DropDown.new_from_strings([self.cfg["device"] or cast_targets.CHOOSE_RECEIVER])
        self.device_dropdown.set_hexpand(True)
        self.device_dropdown.connect("notify::selected", self._on_device_selected)
        refresh = self._icon_button(
            "view-refresh-symbolic", "Scan the network", "flat", self.scan_devices,
        )
        refresh.set_valign(Gtk.Align.CENTER)
        row.append(self.device_dropdown)
        row.append(refresh)
        body.append(row)
        manual = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cast_ip_entry = Gtk.Entry()
        self.cast_ip_entry.set_placeholder_text("Cast receiver IPv4 (e.g. 192.168.1.40)")
        self.cast_ip_entry.set_hexpand(True)
        self.cast_ip_entry.set_tooltip_text(
            "For Cast-enabled TVs not found by mDNS discovery. DLNA and AirPlay require other backends."
        )
        self.cast_ip_entry.connect("activate", lambda _entry: self._add_cast_target())
        self.add_ip_button = Gtk.Button(label="Add IP")
        self.add_ip_button.add_css_class("flat")
        self.add_ip_button.connect("clicked", lambda _button: self._add_cast_target())
        manual.append(self.cast_ip_entry)
        manual.append(self.add_ip_button)
        body.append(manual)
        # Explicit opt-in: no connection probes during UI creation or normal tests.
        self.network_check_button = Gtk.Button(label="Check connection")
        self.network_check_button.add_css_class("flat")
        self.network_check_button.connect(
            "clicked", lambda _button: network_route_ui.start(self, Async.run)
        )
        body.append(self.network_check_button)
        self.network_detail = Gtk.Label(
            label="", xalign=0.0, wrap=False,
            ellipsize=Pango.EllipsizeMode.END,
        )
        self.network_detail.set_selectable(True)  # Copy second-host test URL.
        self.network_detail.add_css_class("section-caption")
        body.append(self.network_detail)
        self.device_detail = Gtk.Label(
            label="Searching for Google Cast receivers…", xalign=0.0,
            wrap=False, ellipsize=Pango.EllipsizeMode.END,
        )
        self.device_detail.add_css_class("section-caption")
        body.append(self.device_detail)
        return card


    def _build_portal_card(self) -> Gtk.Box:
        card, body = self._card(
            "Shared room", "Open this address on a phone on your local network to join the queue and control playback."
        )
        self.portal_status_label = Gtk.Label(
            label="Starting local portal…", xalign=0.0, wrap=False,
            ellipsize=Pango.EllipsizeMode.END,
        )
        self.portal_status_label.add_css_class("section-caption")
        body.append(self.portal_status_label)
        self.portal_activity_label = Gtk.Label(
            label="No client activity", xalign=0.0, wrap=False,
            ellipsize=Pango.EllipsizeMode.END,
        )
        self.portal_activity_label.add_css_class("section-caption")
        body.append(self.portal_activity_label)
        body.append(Gtk.Label(label="Nearby SmoothCast hosts", xalign=0.0))
        self.portal_peers_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4,
        )
        self.portal_peers_box.append(Gtk.Label(
            label="Looking for SmoothCast hosts…", xalign=0.0, wrap=True,
        ))
        body.append(self.portal_peers_box)
        body.append(Gtk.Label(label="Address", xalign=0.0))
        self.portal_url_label = Gtk.Label(
            label="—", xalign=0.0, wrap=False, selectable=True,
            ellipsize=Pango.EllipsizeMode.END,
        )
        self.portal_url_label.add_css_class("mono")
        self.portal_url_label.set_hexpand(True)
        address_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        address_row.append(self.portal_url_label)
        self.portal_copy_button = Gtk.Button(label="Copy link", sensitive=False)
        self.portal_copy_button.connect("clicked", self._copy_portal_link)
        address_row.append(self.portal_copy_button)
        body.append(address_row)
        self.portal_qr_row = Gtk.Box(spacing=8, visible=False)
        self.portal_qr_picture = Gtk.Picture(
            alternative_text="QR code for the room link", can_shrink=False,
        )
        self.portal_qr_row.append(self.portal_qr_picture)
        self.portal_qr_row.append(Gtk.Label(
            label="Scan with your phone camera, then enter the room PIN.",
            xalign=0.0, wrap=True,
        ))
        body.append(self.portal_qr_row)
        connection_hint = Gtk.Label(
            label="Use the same Wi-Fi. If the link does not open, check your VPN "
                  "or whether guest Wi-Fi blocks connections between devices.",
            xalign=0.0, wrap=True,
        )
        connection_hint.add_css_class("dim-label")
        body.append(connection_hint)
        body.append(Gtk.Label(label="6-digit room PIN", xalign=0.0))
        self.portal_pin_label = Gtk.Label(label="—", xalign=0.0, selectable=True)
        self.portal_pin_label.add_css_class("hero-title")
        self.portal_pin_label.add_css_class("mono")
        body.append(self.portal_pin_label)
        note = Gtk.Label(
            label="Anyone with this PIN can join the queue, vote and control playback. "
                  "The PIN changes when the portal restarts.",
            xalign=0.0, wrap=False, ellipsize=Pango.EllipsizeMode.END,
        )
        note.add_css_class("dim-label")
        body.append(note)
        guest_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.portal_guest_ids: tuple[str, ...] = ()
        self.portal_guest_dropdown = Gtk.DropDown.new_from_strings(["No guests connected"])
        self.portal_guest_dropdown.set_hexpand(True)
        self.portal_guest_dropdown.set_sensitive(False)
        self.portal_guest_dropdown.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Select a room guest to revoke"]
        )
        self.portal_revoke_button = Gtk.Button(label="Remove guest")
        self.portal_revoke_button.set_sensitive(False)
        self.portal_revoke_button.connect("clicked", self._portal_revoke_selected)
        guest_row.append(self.portal_guest_dropdown)
        guest_row.append(self.portal_revoke_button)
        body.append(guest_row)
        self.portal_end_access_button = Gtk.Button(label="End guest access / New PIN")
        self.portal_end_access_button.add_css_class("destructive-action")
        self.portal_end_access_button.set_tooltip_text(
            "Sign out all guests and generate a new PIN; playback continues")
        self.portal_end_access_button.connect(
            "clicked", self._portal_confirm_end_access)
        body.append(self.portal_end_access_button)
        return card

    def _build_details_card(self) -> Gtk.Box:
        card, body = self._card(
            "Stream diagnostics", "A live technical readout of the current session."
        )
        card.add_css_class("diagnostics-card")
        grid = Gtk.Grid(row_spacing=11, column_spacing=16)
        grid.set_valign(Gtk.Align.START)
        grid.set_column_homogeneous(False)
        self.detail_labels: dict[str, Gtk.Label] = {}
        rows = [
            ("state", "State"), ("mode", "Mode"), ("encoder", "Encoder"),
            ("position", "Position"), ("buffer", "Buffer health"), ("segments", "Segments"),
            ("resolution", "Video"), ("audio", "Audio"),
            ("subs", "Subtitles"), ("file", "File"), ("url", "Stream URL"),
        ]
        row_index = 0
        for index, (key, label) in enumerate(rows):
            if index in (0, 6):
                if index:
                    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                    sep.add_css_class("mini-divider")
                    grid.attach(sep, 0, row_index, 3, 1)
                    row_index += 1
                heading = Gtk.Label(
                    label="PLAYBACK & ENCODER" if index == 0 else "MEDIA & OUTPUT",
                    xalign=0.0,
                )
                heading.add_css_class("detail-section")
                grid.attach(heading, 0, row_index, 3, 1)
                row_index += 1
            key_label = Gtk.Label(label=label, xalign=0.0)
            key_label.add_css_class("detail-key")
            value_label = Gtk.Label(
                label="—", xalign=0.0, wrap=False, selectable=True,
                ellipsize=Pango.EllipsizeMode.END,
            )
            value_label.set_max_width_chars(32)
            value_label.set_width_chars(1)
            value_label.add_css_class("detail-value")
            grid.attach(key_label, 0, row_index, 1, 1)
            grid.attach(value_label, 1, row_index, 1, 1)
            if key == "url":
                copy_button = self._icon_button(
                    "edit-copy-symbolic", "Copy stream URL", "flat", self._copy_url, size=14
                )
                copy_button.set_valign(Gtk.Align.START)
                copy_button.set_visible(False)
                grid.attach(copy_button, 2, row_index, 1, 1)
                self.copy_url_button = copy_button
            self.detail_labels[key] = value_label
            row_index += 1
        body.append(grid)
        self._buffer_health = buffer_health.BufferHealth()
        self._last_stall_count = 0
        self.buffer_graph = BufferHealthGraph()
        body.append(self.buffer_graph)
        return card


    def _card(self, title: str, subtitle: str = "") -> tuple[Gtk.Box, Gtk.Box]:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("card")
        heading = Gtk.Label(label=title, xalign=0.0)
        heading.add_css_class("heading")
        card.append(heading)
        if subtitle:
            sub = Gtk.Label(
                label=subtitle, xalign=0.0, wrap=False,
                ellipsize=Pango.EllipsizeMode.END,
            )
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            card.append(sub)
        return card, card


    def _switch_row(self, body, label, subtitle, active, callback) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("setting-row")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=label, xalign=0.0)
        title.add_css_class("label-strong")
        sub = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        box.append(title)
        box.append(sub)
        box.set_hexpand(True)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.set_active(active)
        switch.connect("notify::active", callback)
        switch.subtitle_label = sub
        row.append(box)
        row.append(switch)
        body.append(row)
        return switch


    def _icon_button(self, icon, tooltip, style_class, callback, size=16) -> Gtk.Button:
        button = Gtk.Button()
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(size)
        button.set_child(image)
        button.set_tooltip_text(tooltip)
        button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
        for cls in style_class.split():
            button.add_css_class(cls)
        button.connect("clicked", lambda _b: callback())
        return button


    def _text_button(self, label, tooltip, callback) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.set_tooltip_text(tooltip)
        button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
        button.add_css_class("pill")
        button.connect("clicked", lambda _b: callback())
        return button


    def _back_to_start(self) -> None:
        """Send the active cast, or the local preview, back to the start."""
        self.seek_to(0.0)


    def _seek_percent(self, tenth: int) -> None:
        """Seek to a tenth of the current film (transport digit shortcuts)."""
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if not duration and self._preview_path and self.session is None:
            duration = self.queue_durations.get(self._preview_path, 0.0)
        if duration:
            self.seek_to(duration * tenth / 10.0)


    def _install_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()

        def add(accel, callback):
            trigger = Gtk.ShortcutTrigger.parse_string(accel)
            action = Gtk.CallbackAction.new(lambda *args: (callback(), True)[1])
            controller.add_shortcut(Gtk.Shortcut.new(trigger, action))

        add("space", self.toggle_play)
        add("k", self.toggle_play)
        add("Home", self._back_to_start)
        add("Left", self._skip_back10)
        add("Right", self._skip_forward10)
        add("comma", self._skip_back1)
        add("period", self._skip_forward1)
        add("<Shift>Left", self._skip_back30)
        add("<Shift>Right", self._skip_forward30)
        add("j", self._skip_back10)
        add("l", self._skip_forward10)
        add("m", self.toggle_mute)
        add("Up", lambda: self._nudge_volume(5))
        add("Down", lambda: self._nudge_volume(-5))
        add("g", lambda: self._adjust_subtitle_delay(-1))
        add("h", lambda: self._adjust_subtitle_delay(1))
        add("<Shift>g", lambda: self._adjust_audio_delay(-1))
        add("<Shift>h", lambda: self._adjust_audio_delay(1))
        add("s", self.stop_stream)
        add("p", self.on_prev)
        add("n", self.on_next)
        add("<Control>f", lambda: self.queue_search.grab_focus())
        for digit in range(1, 10):
            add(str(digit), lambda d=digit: self._seek_percent(d))
        self.add_controller(controller)


    def _remember_normal_geometry(self) -> None:
        self._last_normal_size = responsive_layout.remember_normal_size(
            self.get_width(), self.get_height(), self._last_normal_size,
            fullscreen=self.is_fullscreen(), maximized=self.is_maximized(),
        )

    def _refresh_responsive_layout(self) -> bool:
        """Reflow once per actual size/mode change; never do I/O during resize."""
        width = self.get_width() or self._startup_width
        height = self.get_height() or self._startup_height
        self._remember_normal_geometry()
        state = responsive_layout.layout_for_size(width, height, self.cfg.get("density"))
        if width < text_fit.NARROW_WIDTH:
            text_fit.fit_labels(self)  # long text wraps/ellipsizes instead of widening the window (#136)
        if state == self._layout_state:
            return True
        self._layout_state = state

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
        self.right_column.set_hexpand(state.stacked)

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
        for child in self.transport_controls:
            self.transport_grid.remove(child)
        if state.transport_wrapped:
            positions = ((0, 0), (1, 1), (1, 0), (2, 0),
                         (3, 0), (2, 1), (4, 0), (3, 1))
        else:
            positions = tuple((n, 0) for n in range(len(self.transport_controls)))
        for button, (column, row) in zip(self.transport_controls, positions):
            self.transport_grid.attach(button, column, row, 1, 1)

        for child in self.action_controls:
            self.action_grid.remove(child)
        self.action_grid.set_column_homogeneous(state.actions_wrapped)
        for n, child in enumerate(self.action_controls):
            col, row = (n % 2, n // 2) if state.actions_wrapped else (n, 0)
            self.action_grid.attach(child, col, row, 1, 1)
        return True


    def _apply_color_scheme(self) -> None:
        if self.cfg.get("auto_theme"):
            import datetime
            dark = ui_theme.is_dark_hour(datetime.datetime.now().hour)
            scheme = Adw.ColorScheme.PREFER_DARK if dark else Adw.ColorScheme.FORCE_LIGHT
            Adw.StyleManager.get_default().set_color_scheme(scheme)
            return
        scheme = {
            "default": Adw.ColorScheme.DEFAULT,
            "force-light": Adw.ColorScheme.FORCE_LIGHT,
            "prefer-dark": Adw.ColorScheme.PREFER_DARK,
        }.get(self.cfg["color_scheme"], Adw.ColorScheme.PREFER_DARK)
        Adw.StyleManager.get_default().set_color_scheme(scheme)


    def _set_device_badge(self, label: str, state: str = "") -> None:
        badge = self.device_status_badge
        previous_label = badge.get_text()
        for previous_class in ("online", "offline"):
            badge.remove_css_class(previous_class)
        if state in ("online", "offline"):
            badge.add_css_class(state)
        badge.set_text(label)
        if label == "OFFLINE" and previous_label != "OFFLINE" and (
                self.session is not None or self.external):
            self._notify(notifications.DEVICE_LOST, self._device())


    def _notify(self, event: str, detail: str = "") -> None:
        """Post a desktop notification without presenting or focusing the window."""
        try:
            active = bool(self.is_active())
        except Exception:
            active = False
        if not notifications.should_notify(self.cfg, event, window_active=active):
            return
        if event == notifications.FINISHED:
            title = "Playback finished"
            name = pathlib.Path(detail).name if detail else ""
            body = f"{name} finished playing." if name else "The cast finished."
        elif event == notifications.ERROR:
            title = "Cast failed"
            body = detail or "The cast failed."
        else:
            title = "Receiver lost"
            body = f"{detail} stopped responding." if detail else "The receiver stopped responding."
        try:
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            self.app.send_notification(None, notification)
        except Exception as exc:
            self._console(f"Notification unavailable: {exc}")


    def _set_chip(self, label: str, kind: str) -> None:
        for existing in ("idle", "playing", "paused", "buffering", "offline", "error"):
            self.state_chip.remove_css_class(existing)
        self.state_chip.add_css_class(kind)
        self.state_chip.set_text(label)


    def _set_levels_hint(self, text: str) -> None:
        hint = getattr(self, "levels_hint", None)
        if hint is not None:
            hint.set_text(text or "Meter becomes active while analysing audio.")


    def _console(self, text: str) -> None:
        """Append a timestamped line to the live casting status console."""
        import datetime
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.console_lines.append(f"[{stamp}] {text}")
        # Keep the console bounded so it never grows unboundedly.
        if len(self.console_lines) > 200:
            self.console_lines = self.console_lines[-200:]
        if getattr(self, "console_list", None) is not None:
            self._refresh_console()


    def _clear_console(self) -> None:
        self.console_lines = []
        self._refresh_console()


    def _refresh_console(self) -> None:
        list_box = self.console_list
        for child in list(list_box):
            list_box.remove(child)
        has_activity = bool(self.console_lines)
        self.console_empty.set_visible(not has_activity)
        self.console_scroller.set_visible(has_activity)
        self.console_clear_button.set_sensitive(has_activity)
        for line in self.console_lines[-60:]:
            text = Gtk.Label(label=line, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
            text.add_css_class("console-line")
            text.set_tooltip_text(line)
            text.set_selectable(True)
            list_box.append(text)


    def _update_details(self, snapshot: progress_model.Progress | None = None) -> None:
        info = self.device_info
        session = self.session
        media = self.media
        # Reuse the snapshot the seekbar used this tick; neither path touches
        # the filesystem (a background Session sampler maintains the cache).
        if snapshot is None:
            snapshot = session.progress() if session else progress_model.EMPTY
        state_text = {
            "OFFLINE": "Offline",
            "IDLE": "Idle",
            "PLAYING": "Playing",
            "BUFFERING": "Buffering",
            "PAUSED": "Paused",
        }.get(self.device_state, self.device_state.title())
        if self.external:
            state_text += " (external stream)"
        mode_text = "—"
        encoder_text = "—"
        if session and session.state:
            mode_text = ("DLNA progressive MP4" if session.mode == "dlna" else (
                "Direct play (buffered)" if session.mode == "direct" else "Live transcode (HLS)"))
            if session.mode == "transcode":
                speed, fps = snapshot.speed_text, snapshot.fps_text
                engine = "libx264 (CPU)" if session.used_software_fallback else "h264 VAAPI"
                encoder_text = f"{engine} · {speed} · {fps} fps"
            else:
                encoder_text = "local MP4 preparation" if session.mode == "dlna" else "device-native"
        if self.external and info:
            title = f"{str(info.get('title') or 'external stream')} · external"
            if self.np_title.get_text() != title:
                self.np_title.set_text(title)
            hint = "Another app started this stream — controls are limited"
            if self.np_meta.get_text() != hint:
                self.np_meta.set_text(hint)
        position = self.tracker.value()
        position_text = "unknown" if position is None else f"{fmt_time(position)} of {fmt_time(self.tracker.duration)}"
        if self.tracker.known and session and session.mode == "transcode":
            position_text += " (estimated)"
        # Buffer health — how far ahead the encoder is from playback position.
        buffer_text = "—"
        ahead = None
        if session and session.mode == "transcode" and session.state:
            encoded = playback_state.absolute_encoded_position(
                session.state.offset, snapshot.out_time,
                self.tracker.duration or (media.duration if media else 0.0),
                speed=session.state.speed,
            )
            if encoded is not None and position is not None:
                ahead = encoded - position
                if ahead >= 0:
                    buffer_text = f"{fmt_time(ahead)} ahead"
                else:
                    buffer_text = f"{fmt_time(-ahead)} behind"
        # Segment count for HLS streams.
        segments_text = "—"
        seg_count = 0
        if session and session.mode == "transcode":
            seg_count = session.segment_count()
            segments_text = f"{seg_count} segment{'s' if seg_count != 1 else ''}"
        if session and session.mode == "transcode" and session.state:
            restarts = getattr(self._stream_watchdog, "restarts", 0)
            if restarts < self._last_stall_count:
                self._last_stall_count = restarts
            stalled = restarts > self._last_stall_count
            self._last_stall_count = restarts
            self._buffer_health.sample(ahead, seg_count, stalled=stalled)
        else:
            self._buffer_health.clear()
        self.buffer_graph.set_health(self._buffer_health)
        subtitle_text = "—"
        if session and session.state:
            if session.state.embedded_subtitle_index >= 0:
                track = next((t for t in media.subtitle_tracks
                              if t.index == session.state.embedded_subtitle_index), None) if media else None
                subtitle_text = f"{track.label if track else 'MKV'} (burned in)"
            elif session.state.subs:
                subtitle_text = pathlib.Path(session.state.subs).name + (" (burned in)" if session.state.burn_subs else "")
            else:
                subtitle_text = "off"
        elif self._active_subs():
            subtitle_text = pathlib.Path(self._active_subs()).name + " (ready)"
        else:
            subtitle_text = "off"
        url_text = session.state.stream_url if session and session.state and session.state.stream_url else "—"
        media_text = "—"
        if media:
            if media.is_audio_only:
                media_text = "Audio only"
            else:
                bits = [media.resolution, media.vcodec, media.pix_fmt]
                if media.size_label:
                    bits.append(media.size_label)
                media_text = " · ".join(bit for bit in bits if bit)
        audio_text = "—"
        if media:
            parts = [media.acodec or "unknown audio"]
            if media.channels:
                parts.append(f"{media.channels}ch")
            if media.audio_tracks > 1:
                parts.append(f"{media.audio_tracks} tracks")
            audio_text = " · ".join(parts)
        file_text = pathlib.Path(session.state.file).name if session and session.state else (
            pathlib.Path(self.now_playing).name if self.now_playing else "—"
        )
        values = {
            "state": state_text,
            "mode": mode_text,
            "encoder": encoder_text,
            "position": position_text,
            "buffer": buffer_text,
            "segments": segments_text,
            "resolution": media_text,
            "audio": audio_text,
            "subs": subtitle_text,
            "file": file_text,
            "url": url_text,
        }
        for key, value in values.items():
            label = self.detail_labels.get(key)
            if label is not None and label.get_text() != value:
                label.set_text(value)
                if key in ("file", "url"):
                    label.set_tooltip_text(value if value != "—" else None)
        url_available = bool(url_text and url_text != "—")
        if self.copy_url_button.get_visible() != url_available:
            self.copy_url_button.set_visible(url_available)
        if media is not None and not (session and session.state):
            self._set_now_playing_labels(media, None)
        self.subs_detail.set_text(self._subs_status_text())


    def _set_now_playing_labels(self, media, session) -> None:
        title = pretty_title(media.path)
        meta = ([f"Audio · {media.acodec or 'unknown codec'}"]
                if media.is_audio_only else [media.resolution])
        if media.duration:
            meta.append(fmt_time(media.duration))
        if media.is_audio_only and media.channels:
            meta.append(f"{media.channels}ch")
        if media.vcodec:
            meta.append(media.vcodec)
        if media.size_label:
            meta.append(media.size_label)
        if session is not None and session.state:
            meta.append("DLNA/UPnP" if session.mode == "dlna" else (
                "direct play" if session.mode == "direct" else "live transcode"))
        text = " · ".join(bit for bit in meta if bit)
        if self.np_title.get_text() != title:
            self.np_title.set_text(title)
            self.np_title.set_tooltip_text(str(media.path))
        if self.np_meta.get_text() != text:
            self.np_meta.set_text(text)


    def _update_header_subtitle(self) -> None:
        labels = {
            "OFFLINE": "offline",
            "IDLE": "idle",
            "PLAYING": "playing",
            "BUFFERING": "buffering",
            "PAUSED": "paused",
        }
        state = labels.get(self.device_state, "idle")
        if self.external and state not in {"offline", "idle"}:
            state = "playing on TV"
        device = self._device()
        subtitle = f"{device} · {state}" if device else "No receiver selected"
        tooltip = f"Running {APP_NAME} {version.label()}"
        if self.update_notice:
            subtitle += " · restart to update"
            tooltip += f"\n{self.update_notice}"
        self.title_widget.set_subtitle(subtitle)
        self.title_widget.set_tooltip_text(tooltip)


    def _update_transport_icon(self) -> None:
        playing = self.device_state in {"PLAYING", "BUFFERING"}
        if self.session is None and not self.external:
            stream = self._local_stream()
            playing = bool(stream is not None and stream.get_playing())
        name = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        if self._play_icon_name != name:
            self._play_icon_name = name
            self.play_image.set_from_icon_name(name)


    def toast(self, message: str, *, error: bool = False) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(3 if not error else 5)
        if error:
            toast.set_priority(Adw.ToastPriority.HIGH)
        self.toasts.add_toast(toast)


    def _copy_url(self) -> None:
        url = self.detail_labels["url"].get_text()
        if url and url != "—":
            self.get_clipboard().set(url)
            self.toast("Stream URL copied")


    def _refresh_controls(self) -> None:
        online = self.device_state != "OFFLINE"
        playing = self.device_state in {"PLAYING", "BUFFERING"}
        paused = self.device_state == "PAUSED"
        busy = self.busy
        # Keep transport enabled until the receiver finishes its buffered HLS.
        active = bool(self.session is not None and self.session.state is not None) or self.external
        ready_to_cast = self.now_playing is not None or (
            self.selected_index is not None and 0 <= self.selected_index < len(self.queue)
        )
        self.cast_button.set_sensitive(ready_to_cast and online and not busy)
        # Make the next useful action unmistakable: Open when empty, Cast when
        # a local video is ready. Avoid a bright, inert Cast button on startup.
        if ready_to_cast:
            self.open_button.remove_css_class("primary-action")
            self.cast_button.add_css_class("primary-action")
        else:
            self.cast_button.remove_css_class("primary-action")
            self.open_button.add_css_class("primary-action")
        self.stop_tv_button.set_sensitive(active and not busy)
        local_ready = self._preview_path is not None and self.session is None and not self.external
        can_play = not busy and ((online and active) or local_ready)
        self.play_button.set_sensitive(can_play)
        self.stop_button.set_sensitive(
            (not busy and ((online and active) or local_ready))
            or (busy and self._dlna_cancel is not None)
        )
        can_seek = not busy and ((online and not self.external and self.tracker.known and active)
                                 or (local_ready and bool(self.media and self.media.duration)))
        for button in (self.start_button, self.back10_button, self.back30_button,
                       self.fwd10_button, self.fwd30_button):
            button.set_sensitive(can_seek)
        has_queue = bool(self.queue)
        index = self.queue.index(self.now_playing) if self.now_playing in self.queue else None
        self.prev_button.set_sensitive(not busy and (has_queue and (index is None or index > 0) or active))
        self.next_button.set_sensitive(not busy and has_queue and index is not None and index + 1 < len(self.queue))
        has_volume = online and self._volume_control_available()
        for control in (self.volume_scale, self.mute_button):
            control.set_sensitive(has_volume)
        # Sensitivity is user feedback, not the security/ownership guard:
        # callbacks must independently reject changes during a cast.
        target_locked = bool(self.session is not None or self.busy
                             or self._cast_starting or self.external)
        self.device_dropdown.set_sensitive(not target_locked)
        self.cast_ip_entry.set_sensitive(not target_locked)
        self.add_ip_button.set_sensitive(not target_locked)
        self.device_dropdown.set_tooltip_text(
            "Stop the current cast before changing TVs" if target_locked
            else "Choose a Cast or DLNA receiver"
        )
        embedded_burned = bool(
            self.session and self.session.state
            and self.session.state.embedded_subtitle_index >= 0
        )
        subtitle_burned = bool(self.session and self.session.state and self.session.state.burn_subs)
        dlna_active = bool(self.session and self.session.mode == "dlna")
        self.cc_button.set_sensitive(active and not busy and not subtitle_burned and not dlna_active)
        self.cc_button.set_tooltip_text(
            "DLNA captions are prepared in the MP4; recast to change them"
            if dlna_active else (
                "Captions are burned into video; change settings and recast to switch off"
                if subtitle_burned else "Toggle subtitles on the receiver"
            )
        )
        has_subs = (embedded_burned or bool(self._active_subs())
                    or bool(self.session and self.session.state and self.session.state.subs))
        self._syncing = True
        self.cc_button.set_active(has_subs and self.cfg["subs"] != "off")
        self._syncing = False
        self.local_button.set_sensitive(local_ready and not busy)
        stream = self._local_stream()
        if stream is not None and stream.get_playing():
            self.local_button.set_label("Pause preview")
        else:
            self.local_button.set_label("Play preview")
        if self.session is None and not self.external and stream is not None and stream.get_playing():
            self._set_chip("Playing locally", "playing")
        elif local_ready:
            self._set_chip("Preview paused" if stream is not None else "Ready to preview", "idle")
        elif self.device_state == "OFFLINE":
            self._set_chip("Offline", "offline")
        elif self.busy:
            self._set_chip("Preparing…", "buffering")
        elif self.external:
            self._set_chip("External", "paused")
        elif self.device_state == "BUFFERING":
            self._set_chip("Buffering…", "buffering")
        elif playing:
            self._set_chip("Live" if (self.session and self.session.mode == "transcode") else "Playing", "playing")
        elif paused:
            self._set_chip("Paused", "paused")
        else:
            if stream is not None and stream.get_playing():
                self._set_chip("Playing locally", "playing")
            elif local_ready:
                self._set_chip("Ready to preview", "idle")
            else:
                self._set_chip("Ready", "idle")


    def _refresh_direct_note(self) -> None:
        switch = getattr(self, "direct_switch", None)
        label = getattr(switch, "subtitle_label", None) if switch is not None else None
        if label is None:
            return
        if self.cfg["direct"] and self.cfg["audio"] != "original":
            label.set_text("Ignored while a sound enhancement is selected — the "
                           "enhancer needs the transcode pipeline")
        else:
            label.set_text("Instant seeking for H.264/AAC files")


    def _toggle_favourite(self) -> None:
        """Pin/unpin the selected file; ordered list, separate from recents."""
        path = self._selected_path()
        if not path:
            self.toast("Select a file to pin", error=True)
            return
        favourites = [p for p in self.cfg.get("favourites", []) if p != path]
        pinned = len(favourites) == len(self.cfg.get("favourites", []))
        if pinned:
            favourites.insert(0, path)
        self.cfg["favourites"] = favourites[:16]
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast(f"{'Pinned' if pinned else 'Unpinned'}: {pathlib.Path(path).name}")


    def _clear_favourites(self) -> None:
        self.cfg["favourites"] = []
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast("Favourites cleared")


    def _open_favourite(self, index: int) -> None:
        favourites = self.cfg.get("favourites", [])
        if not 0 <= index < len(favourites):
            return
        path = pathlib.Path(favourites[index])
        if not path.is_file():
            self.toast("That file has moved or been deleted", error=True)
            return
        self.open_paths([str(path)])


    def _note_device_used(self) -> None:
        """Remember the last successful receiver so the picker can sort by it."""
        self.cfg["device_last_used"] = cast_targets.record_use(
            self.cfg.get("device_last_used"), self.cfg.get("device", ""), time.time())
        save_config(self.cfg)


    def _toggle_device_favourite(self) -> None:
        """Pin/unpin the current receiver so it stays at the top of the picker."""
        device = self.cfg.get("device", "")
        if not device:
            return
        favourites = [d for d in self.cfg.get("device_favourites", []) if d != device]
        pinned = len(favourites) == len(self.cfg.get("device_favourites", []))
        if pinned:
            favourites.insert(0, device)
        self.cfg["device_favourites"] = favourites[:16]
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast(f"{'Pinned' if pinned else 'Unpinned'} receiver: {device}")


