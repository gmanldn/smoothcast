"""Picture preferences UI extracted to preserve small, navigable GTK modules."""
from __future__ import annotations

from gi.repository import Adw, Gtk

import picture_adjustments
import picture_check
from cast_widgets import save_config


class PicturePreferencesMixin:
    def _picture_spin(self, group, key: str, title: str, step: float) -> None:
        low, high = picture_adjustments.BOUNDS[key]
        row = Adw.ActionRow(
            title=title,
            subtitle="Affects transcoded video on the next cast or restart.",
        )
        control = Gtk.SpinButton.new_with_range(low, high, step)
        control.set_digits(0 if step >= 1 else 2)
        control.set_numeric(True)
        control.update_property([Gtk.AccessibleProperty.LABEL], [title])
        row.add_suffix(control)
        row.set_activatable_widget(control)
        group.add(row)
        self._picture_spins[key] = control
        control.connect("value-changed", lambda spin: self._picture_changed(key, spin))

    def _refresh_picture_preview(self) -> None:
        """Discard stale colour-preview frames without changing live playback."""
        owner = self.owner
        if (getattr(owner, "_preview_path", None) is None
                or getattr(owner, "session", None) is not None
                or getattr(owner, "external", False)):
            return
        owner._preview_generation = getattr(owner, "_preview_generation", 0) + 1
        owner._queue_preview(getattr(owner, "_preview_position", 0.0))

    def _picture_changed(self, key: str, spin) -> None:
        if self._syncing:
            return
        self.owner.cfg[key] = picture_adjustments.validated(key, spin.get_value())
        save_config(self.owner.cfg)
        self._refresh_picture_preview()

    def _reset_picture(self, _button) -> None:
        self.owner.cfg.update(picture_adjustments.DEFAULTS)
        save_config(self.owner.cfg)
        self.sync_from_owner()
        self._refresh_picture_preview()

    def _build_picture_preferences(self, playback, output) -> None:
        picture = self._group(
            playback, "Colour adjustments",
            "Optional FFmpeg adjustments for transcoded output. Neutral settings "
            "preserve the source; changing a value disables direct play for that cast.",
        )
        for key, title, step in (
            ("picture_brightness", "Brightness", 0.05),
            ("picture_contrast", "Contrast", 0.05),
            ("picture_saturation", "Saturation", 0.05),
            ("picture_hue", "Hue (degrees)", 5),
        ):
            self._picture_spin(picture, key, title, step)
        reset_row = Adw.ActionRow(title="Restore original colours")
        reset_button = Gtk.Button(label="Reset picture")
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.connect("clicked", self._reset_picture)
        reset_row.add_suffix(reset_button)
        reset_row.set_activatable_widget(reset_button)
        picture.add(reset_row)
        self.picture = picture_check.PictureCheck(self.owner)
        output.add(self.picture.row)


