"""Fullscreen idle-chrome auto-hide policy and controller (#119).

The window hides its header bar after a short idle period in fullscreen and
reveals it on pointer motion, key presses, focus changes and accessibility or
visibility changes. The decision policy is pure so it can be tested headlessly,
and the timer only runs while fullscreen, so idle desktop sessions do no extra
work. GTK is imported lazily so CLI-only modules never load it.
"""

import time

IDLE_SECONDS = 2.5
REVEAL_EVENTS = frozenset({"motion", "key", "focus", "accessibility"})


def should_hide(*, fullscreen: bool, active: bool, idle_seconds: float,
                timeout: float = IDLE_SECONDS) -> bool:
    """Hide chrome only when fullscreen, focused and genuinely idle."""
    return bool(fullscreen and active and idle_seconds >= timeout)


def is_reveal_event(event: str) -> bool:
    """Return whether an event should bring the hidden chrome back."""
    return event in REVEAL_EVENTS


class IdleChrome:
    """Hide a chrome widget while fullscreen is idle and reveal it on input."""

    def __init__(self, window, chrome, *, seconds: float = IDLE_SECONDS,
                 clock=time.monotonic, install: bool = True,
                 schedule=None, unschedule=None) -> None:
        self.window = window
        self.chrome = chrome
        self.seconds = seconds
        self._clock = clock
        self._schedule = schedule
        self._unschedule = unschedule
        self._source = 0
        self._last_activity = clock()
        if install:
            self._install()

    def _install(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self.reveal("motion"))
        self.window.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", lambda *_: (self.reveal("key"), False)[1])
        self.window.add_controller(keys)
        self.window.connect("notify::is-active", lambda *_: self.reveal("focus"))
        self.window.connect("notify::visible", lambda *_: self.reveal("accessibility"))
        self.window.connect("notify::focus-widget", lambda *_: self.reveal("accessibility"))
        self.window.connect("notify::fullscreened", lambda *_: self._mode_changed())

    def _mode_changed(self) -> None:
        if self.window.is_fullscreen():
            self.arm()
        else:
            self.cancel()
            self.show()

    def _arm_source(self) -> int:
        if self._schedule is None:
            from gi.repository import GLib

            self._schedule = GLib.timeout_add
            self._unschedule = GLib.source_remove
        return self._schedule(250, self._tick)

    def arm(self) -> None:
        self.cancel()
        self._last_activity = self._clock()
        self._source = self._arm_source()

    def cancel(self) -> None:
        if self._source:
            if self._unschedule is None:
                from gi.repository import GLib

                self._unschedule = GLib.source_remove
            self._unschedule(self._source)
            self._source = 0

    def reveal(self, event: str = "motion") -> None:
        if not is_reveal_event(event):
            return
        self.show()
        self._last_activity = self._clock()
        if self.window.is_fullscreen() and not self._source:
            self._source = self._arm_source()

    def show(self) -> None:
        self.chrome.set_visible(True)

    def hide(self) -> None:
        self.chrome.set_visible(False)

    def _tick(self) -> bool:
        if not self.window.is_fullscreen():
            self._source = 0
            return False
        idle = self._clock() - self._last_activity
        if should_hide(fullscreen=True, active=bool(self.window.is_active()),
                       idle_seconds=idle, timeout=self.seconds):
            self.hide()
            self._source = 0
            return False
        return True
