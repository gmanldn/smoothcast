"""Updates-group row for Preferences: running build, channel and Check now (#579).

Split from ``preferences_ui`` to keep it small. Read-only: nothing here installs
or restarts; the network check runs off the GTK thread via ``update_facts``.
"""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

_ROOT = Path(__file__).resolve().parent.parent


class UpdatePreferencesMixin:
    def _build_update_row(self, group) -> None:
        self.update_status_row = Adw.ActionRow(title="Current version", subtitle="")
        self.update_status_row.set_subtitle_lines(0)
        self.update_check_button = Gtk.Button(label="Check now", valign=Gtk.Align.CENTER)
        self.update_check_button.set_tooltip_text(
            "Contacts the update source once, read-only. Nothing is installed or restarted.")
        self.update_check_button.connect("clicked", lambda _b: self._check_updates_now())
        self.update_status_row.add_suffix(self.update_check_button)
        group.add(self.update_status_row)

    def _check_updates_now(self) -> None:
        import update_facts
        self.update_check_button.set_sensitive(False)
        self.update_status_row.set_subtitle("Checking for updates… playback is not interrupted.")

        def done(text: str) -> bool:
            self.update_status_row.set_subtitle(text)
            self.update_check_button.set_sensitive(True)
            return False

        update_facts.start_check(dict(self.owner.cfg), _ROOT, lambda text: GLib.idle_add(done, text))

    def _sync_update_status(self, cfg: dict) -> None:
        """Offline, read-only: running build and channel, never a check result."""
        try:
            import update_facts
            import update_status
            status = update_status.describe(update_facts.facts_for_preferences(cfg, root=_ROOT))
            self.update_status_row.set_title(status.running_line)
            self.update_status_row.set_subtitle(
                f"{status.headline}. {status.detail} {status.channel_line}.")
        except Exception:  # noqa: BLE001 - fall back to a plain subtitle
            self.update_status_row.set_subtitle("Version details are unavailable.")
