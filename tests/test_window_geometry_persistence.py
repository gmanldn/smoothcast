"""Window geometry regressions without GTK or desktop display."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from responsive_layout import remember_normal_size, window_size


def test_normal_resize_is_saved_but_temporary_fullscreen_is_not():
    previous = (1024, 700)
    normal = remember_normal_size(840, 600, previous,
                                  fullscreen=False, maximized=False)
    assert normal == (840, 600)
    assert remember_normal_size(3840, 2160, normal,
                                fullscreen=True, maximized=False) == normal
    assert remember_normal_size(1920, 1080, normal,
                                fullscreen=False, maximized=True) == normal


def test_invalid_allocations_cannot_overwrite_saved_normal_window():
    previous = (960, 720)
    for w, h in ((0, 0), (-1, 800), ("NaN", 800),
                 (400, float("inf")), (319, 600), (450, 299), (None, None)):
        assert remember_normal_size(w, h, previous,
                                    fullscreen=False, maximized=False) == previous


def test_clamp_saved_normal_size_after_monitor_change():
    saved = remember_normal_size(1600, 1000, (1180, 760),
                                 fullscreen=False, maximized=False)
    assert window_size(*saved, 1366, 768) == (1161, 652)
    assert window_size(*saved, 600, 400) == (510, 304)


def test_ui_uses_allocation_not_default_size_when_persisting():
    from gui_source import legacy_self
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")
    lifecycle = legacy_self((ROOT / "src" / "cast_lifecycle.py").read_text(encoding="utf-8"))
    session = (ROOT / "src" / "cast_session.py").read_text(encoding="utf-8")
    assert "self.get_width(), self.get_height(), self._last_normal_size" in ui
    assert "width, height = self._last_normal_size" in lifecycle
    assert "width, height = self.get_default_size()" not in lifecycle
    assert session.count("self._remember_normal_geometry()") >= 2
    assert "self.move(" not in lifecycle and "self.move(" not in ui


def test_a_default_or_saved_size_never_looks_like_a_full_screen_window():
    import cast_widgets  # noqa: F401  (DEFAULTS must stay a modest window)
    width, height = cast_widgets.DEFAULTS["window_width"], cast_widgets.DEFAULTS["window_height"]
    assert (width, height) == (1180, 760)
    for screen in ((1366, 768), (1920, 1080), (2560, 1440), (3840, 2160), (1280, 720)):
        w, h = window_size(1600, 1000, *screen)
        assert w <= screen[0] * 0.85 and h <= screen[1] * 0.85, screen
    w, h = window_size(width, height, 1920, 1080)
    assert (w, h) == (1180, 760)  # a normal desktop keeps the modest default
