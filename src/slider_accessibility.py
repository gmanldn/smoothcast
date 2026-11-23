"""GTK-free spoken values for the seekbar and volume slider (#449).

The seekbar is a custom ``Gtk.DrawingArea``, so GTK cannot derive a value for
assistive technology; the volume ``Gtk.Scale`` reports a bare number.  These
helpers publish ``VALUE_TEXT`` such as "1:02:03 of 2:05:00" and "50 percent".
A widget is updated only when its spoken text changes (about once a second
during playback), so the GUI tick stays cheap.  Callers pass the ``Gtk``
namespace so ordinary tests never import GTK.
"""
from __future__ import annotations

import math

import castctl


def position_text(position: float | None, duration: float | None) -> str:
    """Return the spoken playback position, e.g. ``1:02:03 of 2:05:00``."""
    total = _finite(duration)
    if total <= 0:
        return "No media playing"
    here = min(_finite(position), total)
    return f"{castctl.fmt_time(here)} of {castctl.fmt_time(total)}"


def sync_position(seekbar, gtk, position: float | None, duration: float | None) -> None:
    """Expose range, value and spoken position of the seekbar."""
    total = max(0.0, _finite(duration))
    now = min(max(0.0, _finite(position)), total)
    text = position_text(position, duration)
    if getattr(seekbar, "_spoken_value", None) == text:
        return
    seekbar._spoken_value = text
    prop = gtk.AccessibleProperty
    seekbar.update_property(
        [prop.VALUE_MIN, prop.VALUE_MAX, prop.VALUE_NOW, prop.VALUE_TEXT],
        [0.0, total, now, text],
    )


def sync_percent(scale, gtk, value: float | None) -> None:
    """Expose a 0-100 slider value as ``N percent`` (range comes from GTK)."""
    percent = int(min(100.0, max(0.0, _finite(value))))
    text = f"{percent} percent"
    if getattr(scale, "_spoken_value", None) == text:
        return
    scale._spoken_value = text
    scale.update_property([gtk.AccessibleProperty.VALUE_TEXT], [text])


def _finite(value: float | None) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0
