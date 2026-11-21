"""Headless regression tests for fullscreen idle-chrome auto-hide (#119)."""

from pathlib import Path

import idle_chrome

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeWindow:
    def __init__(self, *, fullscreen=False, active=True):
        self.fullscreen = fullscreen
        self.active = active

    def is_fullscreen(self):
        return self.fullscreen

    def is_active(self):
        return self.active


class FakeChrome:
    def __init__(self):
        self.visible = True

    def set_visible(self, visible):
        self.visible = visible


def make(*, fullscreen=False, active=True):
    clock = Clock()
    window = FakeWindow(fullscreen=fullscreen, active=active)
    chrome = FakeChrome()
    scheduled = []
    cancelled = []
    controller = idle_chrome.IdleChrome(
        window, chrome, clock=clock, install=False,
        schedule=lambda _ms, callback: scheduled.append(callback) or len(scheduled),
        unschedule=lambda source: cancelled.append(source),
    )
    return controller, window, chrome, clock, scheduled, cancelled


def test_should_hide_only_when_fullscreen_focused_and_idle():
    assert idle_chrome.should_hide(
        fullscreen=True, active=True, idle_seconds=idle_chrome.IDLE_SECONDS)
    assert not idle_chrome.should_hide(
        fullscreen=False, active=True, idle_seconds=10.0)
    assert not idle_chrome.should_hide(
        fullscreen=True, active=False, idle_seconds=10.0)
    assert not idle_chrome.should_hide(
        fullscreen=True, active=True, idle_seconds=0.1)


def test_reveal_events_are_allow_listed():
    for event in idle_chrome.REVEAL_EVENTS:
        assert idle_chrome.is_reveal_event(event)
    assert not idle_chrome.is_reveal_event("scroll")


def test_reveal_shows_and_arms_only_in_fullscreen():
    controller, window, chrome, _clock, scheduled, _cancelled = make(fullscreen=True)
    controller.reveal("motion")
    assert chrome.visible
    assert len(scheduled) == 1
    controller.reveal("key")
    assert len(scheduled) == 1, "a running timer must not be armed twice"

    window.fullscreen = False
    chrome.visible = False
    controller.reveal("motion")
    assert chrome.visible
    assert len(scheduled) == 1


def test_tick_hides_after_idle_and_stops_monitoring():
    controller, _window, chrome, clock, _scheduled, _cancelled = make(fullscreen=True)
    controller.reveal("motion")
    clock.now = idle_chrome.IDLE_SECONDS - 0.1
    assert controller._tick() is True
    assert chrome.visible
    clock.now = idle_chrome.IDLE_SECONDS
    assert controller._tick() is False
    assert not chrome.visible


def test_tick_keeps_chrome_when_unfocused_or_not_fullscreen():
    controller, window, chrome, clock, _scheduled, _cancelled = make(fullscreen=True)
    controller.reveal("motion")
    clock.now = 10.0
    window.active = False
    assert controller._tick() is True
    assert chrome.visible

    window.active = True
    window.fullscreen = False
    assert controller._tick() is False
    assert chrome.visible


def test_leaving_fullscreen_restores_chrome_and_cancels_timer():
    controller, window, chrome, _clock, _scheduled, cancelled = make(fullscreen=True)
    controller.reveal("motion")
    chrome.visible = False
    window.fullscreen = False
    controller._mode_changed()
    assert chrome.visible
    assert cancelled


def test_wiring_and_packaging():
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")
    package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "import idle_chrome" in ui
    assert "self._idle_chrome = idle_chrome.IdleChrome(self, header)" in ui
    assert "notify::fullscreened" in (ROOT / "src" / "idle_chrome.py").read_text("utf-8")
    assert '"idle_chrome"' in package
    assert "Fullscreen idle chrome" in readme


def test_gtk_animation_preference_is_optional_and_changes_live():
    class FakeSettings:
        def __init__(self):
            self.value = True

        def get_property(self, key):
            assert key == "gtk-enable-animations"
            return self.value

    settings = FakeSettings()
    assert idle_chrome.animations_enabled(settings)
    settings.value = False
    assert not idle_chrome.animations_enabled(settings)
    assert idle_chrome.animations_enabled(None)


def test_reduced_motion_wiring_does_not_schedule_meter_animation():
    source = (ROOT / "src" / "cast_widgets.py").read_text()
    assert "self._gtk_settings.connect_object(" in source
    assert "notify::gtk-enable-animations" in source
    assert "if not idle_chrome.animations_enabled(self._gtk_settings):" in source
    assert "GLib.source_remove(self._timer)" in source
    assert "self._start_or_snap()" in source
    assert source.count("GLib.timeout_add(self._TICK_MS, self._animate)") == 1


def test_web_reduced_motion_uses_live_media_query():
    source = (ROOT / "src" / "portal.py").read_text()
    assert "@media(prefers-reduced-motion:reduce)" in source
    assert "animation:none!important" in source
    assert "transition:none!important" in source
