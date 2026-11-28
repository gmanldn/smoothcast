"""Let the isolated GUI smoke keep its window up for an AT-SPI walk (#449).

``SMOOTHCAST_A11Y_HOLD`` is a path prefix set only by ``scripts/gui_a11y_walk.py``
inside the private Xvfb/D-Bus session. The self-test writes ``<prefix>.ready``,
keeps serving its main loop, and quits when ``<prefix>.done`` appears or the
bounded wait ends. Without the variable it quits at once, as before."""
from __future__ import annotations

import os
import time
from pathlib import Path

MAX_HOLD_SECONDS = 60
SCALE_PX_SLACK = 2  # sub-pixel rounding is not clipping


def clipped_labels(window, gtk, checked: list | None = None) -> list[str]:
    """Showing single-line labels whose text is wider than their allocation."""
    found: list[str] = []
    stack = [window]
    while stack:
        widget = stack.pop()
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
        if (isinstance(widget, gtk.Label) and widget.get_mapped() and widget.get_text()
                and not widget.get_wrap() and widget.get_ellipsize() == 0):
            if checked is not None:
                checked.append(1)
            if (widget.get_layout().get_pixel_size()[0] > widget.get_allocated_width() + SCALE_PX_SLACK):
                found.append(widget.get_text()[:60])
    return sorted(set(found))


def _scale_probe(app, prefix: str, gtk) -> None:
    """Opt-in 200% text-scale clip check; result goes to ``<prefix>.scale`` (#449)."""
    import json
    scale = float(os.environ.get("SMOOTHCAST_A11Y_SCALE", "0") or 0)
    if scale <= 1:
        return
    from gi.repository import Gdk
    provider = gtk.CssProvider()
    # root only: "*" compounds per nesting level (1.25**depth) and inflated the window to 18546px
    provider.load_from_string("window { font-size: %d%%; }" % int(scale * 100))
    gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, gtk.STYLE_PROVIDER_PRIORITY_USER)
    window = app.get_active_window() or (app.get_windows() or [None])[0]
    if window is None:
        Path(prefix + ".scale").write_text(json.dumps({"error": "no window"}), encoding="ascii")
        return
    ctx = GLib_ctx()

    def settle() -> None:  # relayout needs frame-clock ticks, not just pending events
        end = time.monotonic() + 1.5
        while time.monotonic() < end:
            while ctx.iteration(False):
                pass
            time.sleep(0.02)

    settle()
    checked: list = []
    clipped = clipped_labels(window, gtk, checked)
    width = window.get_width()
    window.set_default_size(1, 1)  # shrink to the smallest size the layout allows
    settle()
    result = {"scale": scale, "clipped": clipped, "checked": len(checked), "window_width": width,
              "min_width": window.get_width(), "min_height": window.get_height(),
              "min_clipped": clipped_labels(window, gtk)}
    Path(prefix + ".scale").write_text(json.dumps(result), encoding="utf-8")


def GLib_ctx():
    from gi.repository import GLib
    return GLib.MainContext.default()


def quit_when_released(app) -> None:
    prefix = os.environ.get("SMOOTHCAST_A11Y_HOLD")
    if not prefix:
        app.quit()
        return
    from gi.repository import GLib, Gtk
    try:
        _scale_probe(app, prefix, Gtk)
    except Exception as exc:  # noqa: BLE001 - report to the walker, never break the smoke itself
        Path(prefix + ".scale").write_text('{"error": %r}' % str(exc)[:200], encoding="utf-8")
    Path(prefix + ".ready").write_text("1", encoding="ascii")
    deadline = time.monotonic() + MAX_HOLD_SECONDS

    def poll() -> bool:
        if Path(prefix + ".done").exists() or time.monotonic() > deadline:
            app.quit()
            return False
        return True

    GLib.timeout_add(200, poll)
