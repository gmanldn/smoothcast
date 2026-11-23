"""Let long text shrink instead of forcing the window wider (issue #136 / SC-127).

GTK computes a label's minimum width from its full text unless it may wrap or
ellipsize, so under large fonts or a 360 px window a few long labels and button
captions raise the whole window's minimum width and clip everything else. This
walks a widget tree once and lets such labels wrap (plain labels) or ellipsize
(captions inside buttons). It never overrides a label that already wraps or
ellipsizes, so deliberate settings are kept, and it is idempotent.

Measured with real widgets (scripts/gui_checks.py): under 22 pt fonts the
window's minimum width at a 360 px layout drops from 624 px to 360 px.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango

# Below this window width (logical px) the pass is applied; wide windows are untouched.
NARROW_WIDTH = 1000


def fit_labels(root) -> int:
    """Make unconstrained labels shrinkable under *root*; returns how many were changed."""
    changed = 0
    stack = [(root, False)]
    while stack:
        widget, in_button = stack.pop()
        if isinstance(widget, Gtk.Label):
            if in_button:
                if widget.get_ellipsize() == Pango.EllipsizeMode.NONE and not widget.get_wrap():
                    widget.set_ellipsize(Pango.EllipsizeMode.END)
                    changed += 1
            elif widget.get_ellipsize() == Pango.EllipsizeMode.NONE and not widget.get_wrap():
                widget.set_wrap(True)
                widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                changed += 1
        inside = in_button or isinstance(widget, Gtk.Button)
        child = widget.get_first_child()
        while child is not None:
            stack.append((child, inside))
            child = child.get_next_sibling()
    return changed
