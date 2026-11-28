"""Shared-room preferences group (host-editable room name, guest access, port).

Split from ``preferences_ui`` to keep that module within its read budget (#706).
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

import join_slate_ui
from cast_widgets import save_config
from portal_room import clean_room_name


class RoomPreferencesMixin:
    def _build_room_preferences(self, playback) -> None:
        room = self._group(playback, "Playback", "Shared room")
        self.room_name_row = Adw.EntryRow(title="Room name", show_apply_button=True)
        self._saved_room_name = clean_room_name(self.owner.cfg.get("room_name"))
        self.room_name_row.set_text(self._saved_room_name)
        self.room_name_row.connect("apply", self._apply_room_name)
        room.add(self.room_name_row)

        self._switch(room, "portal_screens", "Let room browsers play the queue",
                     "Paired phones and TVs can act as screens or speakers.")
        join_slate_ui.add_switch(self, room)
        self._switch(room, "house_pin_enabled", "Require a house PIN to join",
                     "Only needed if people you don't trust use your Wi-Fi. Applies the next time the room restarts.")
        self._switch(room, "portal_link_youtube", "Let guests acquire YouTube links",
                     "Authorised single videos only. Requires yt-dlp, FFprobe and an isolated "
                     "host worker. Takes effect after a room restart.")
        self._switch(room, "portal_link_magnet", "Let guests acquire BitTorrent magnets",
                     "Authorised public torrents only. Requires aria2c, FFprobe and an isolated "
                     "host worker with restricted network access. Takes effect after a room restart.")
        self._build_link_setup_row(room)
        room_port_row = Adw.ActionRow(
            title="Room remote port",
            subtitle="High-range port used by phone links and QR codes. Change takes effect on the next launch.",
        )
        self.portal_port_spin = Gtk.SpinButton.new_with_range(49152, 65535, 1)
        self.portal_port_spin.set_numeric(True)
        self.portal_port_spin.update_property([Gtk.AccessibleProperty.LABEL], ["Room remote port"])
        room_port_row.add_suffix(self.portal_port_spin)
        room_port_row.set_activatable_widget(self.portal_port_spin)
        self.portal_port_spin.connect("value-changed", self._change_portal_port)
        room.add(room_port_row)

    def _apply_room_name(self, row) -> None:
        name = clean_room_name(row.get_text())
        row.set_text(name)
        self._saved_room_name = name
        if self.owner.cfg.get("room_name") != name:
            self.owner.cfg["room_name"] = name
            save_config(self.owner.cfg)
            self.owner._publish_portal_status()
            self.owner.toast("Room name updated")
