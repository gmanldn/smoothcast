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


def quit_when_released(app) -> None:
    prefix = os.environ.get("SMOOTHCAST_A11Y_HOLD")
    if not prefix:
        app.quit()
        return
    from gi.repository import GLib
    Path(prefix + ".ready").write_text("1", encoding="ascii")
    deadline = time.monotonic() + MAX_HOLD_SECONDS

    def poll() -> bool:
        if Path(prefix + ".done").exists() or time.monotonic() > deadline:
            app.quit()
            return False
        return True

    GLib.timeout_add(200, poll)
