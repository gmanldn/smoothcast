"""Preferences row that installs and attack-tests the link-isolation launcher (#588).

Split from ``preferences_ui``. The blocking work runs in ``link_provision`` off the
GTK thread; this row never enables a provider, it only reports the result.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk


class LinkSetupMixin:
    def _build_link_setup_row(self, group) -> None:
        import link_setup
        reason = link_setup.link_provision.unsupported_reason()
        self.link_setup_row = Adw.ActionRow(title="Set up link isolation")
        self.link_setup_row.set_subtitle_lines(0)
        self.link_setup_row.set_subtitle(
            "Installs the bundled launcher and attack-tests it. Nothing is enabled for guests." if not reason
            else "Not available here: " + reason + ".")
        self.link_setup_button = Gtk.Button(label="Set up", valign=Gtk.Align.CENTER)
        self.link_setup_button.set_sensitive(not reason)
        self.link_setup_button.connect("clicked", lambda _b: self._run_link_setup())
        self.link_setup_row.add_suffix(self.link_setup_button)
        group.add(self.link_setup_row)

    def _run_link_setup(self) -> None:
        import link_setup
        self.link_setup_button.set_sensitive(False)
        self.link_setup_row.set_subtitle("Testing isolation… this takes a few seconds.")

        def done(ok: bool, text: str) -> bool:
            self.link_setup_row.set_subtitle(text)
            self.link_setup_button.set_sensitive(True)
            try:
                import link_diagnostics
                link_diagnostics.describe_switches(self.owner, dict(self.owner.cfg), self._switches)
            except Exception:  # noqa: BLE001 - switch descriptions are best-effort
                pass
            return False

        link_setup.start_setup(lambda ok, text: GLib.idle_add(done, ok, text))
