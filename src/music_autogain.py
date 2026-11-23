"""Small UI and queue helpers for optional audio-only loudness matching."""


def add_settings_switch(body, Gtk, active, changed):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label(label="Music autogain", xalign=0.0, hexpand=True)
    label.add_css_class("label-strong")
    switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    switch.set_tooltip_text(
        "Match audio near -16 LUFS with -1.5 dBTP protection; existing "
        "normalisation takes precedence."
    )
    switch.connect("notify::active", changed)
    row.append(label)
    row.append(switch)
    body.append(row)
    return switch
