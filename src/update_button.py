"""Front-page "Update and restart" button for the desktop window (#711).

Hidden until the shared ``UpdateRunner`` (attached by the portal host) has found a
newer commit on the configured channel. Checks run off the GTK thread at most
every ten minutes; the click asks first when something is playing.
"""
from __future__ import annotations

import threading
import time

from gi.repository import GLib, Gtk

CHECK_EVERY_S = 600.0


def should_check(state: str, last_check: float, now: float) -> bool:
    """Only an idle or settled runner is re-checked, and not more often than the interval."""
    return state in ("idle", "current", "failed", "available") and now - last_check >= CHECK_EVERY_S


def label_for(state: str) -> str | None:
    return {"available": "Update and restart", "updating": "Updating…",
            "restarting": "Restarting…"}.get(state)


class UpdateButton:
    def __init__(self, window: object) -> None:
        self._window = window
        self._last = 0.0
        self.button = Gtk.Button(label="Update and restart", visible=False)
        self.button.add_css_class("suggested-action")
        self.button.set_tooltip_text("Pull the latest SmoothCast and restart it")
        self.button.connect("clicked", self._clicked)

    def refresh(self) -> None:
        runner = getattr(self._window, "update_runner", None)
        if runner is None:
            self.button.set_visible(False)
            return
        snap = runner.snapshot()
        now = time.monotonic()
        if should_check(snap["state"], self._last, now):
            self._last = now
            threading.Thread(target=runner.check, daemon=True, name="update-check").start()
        text = label_for(snap["state"])
        self.button.set_visible(text is not None)
        if text:
            self.button.set_label(text)
            self.button.set_sensitive(snap["state"] == "available")
            self.button.set_tooltip_text(snap["message"])

    def _clicked(self, *_args) -> None:
        runner = getattr(self._window, "update_runner", None)
        if runner is None:
            return
        self.button.set_sensitive(False)

        def work(confirmed: bool) -> None:
            result = runner.apply(confirmed=confirmed)
            GLib.idle_add(self._done, result)

        threading.Thread(target=work, args=(False,), daemon=True, name="update-apply").start()

    def _done(self, result: dict) -> bool:
        runner = self._window.update_runner
        if result.get("needs_confirmation"):
            dialog = Gtk.AlertDialog(message="Update and restart now?", detail=result["message"],
                                     buttons=["Cancel", "Update anyway"], cancel_button=0, default_button=0)

            def answered(dlg, res) -> None:
                try:
                    choice = dlg.choose_finish(res)
                except Exception:
                    choice = 0
                if choice == 1:
                    threading.Thread(target=lambda: GLib.idle_add(self._done, runner.apply(confirmed=True)),
                                     daemon=True, name="update-apply").start()
                else:
                    self.button.set_sensitive(True)

            dialog.choose(self._window, None, answered)
        elif not result.get("ok"):
            self.button.set_sensitive(True)
            self.button.set_tooltip_text(result.get("message", "The update failed."))
        return False
