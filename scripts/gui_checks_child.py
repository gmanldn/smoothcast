#!/usr/bin/env python3
"""In-process GTK behaviour checks; run only by scripts/gui_checks.py.

Executes inside the isolated Xvfb session (private XDG dirs, no desktop display,
no session bus). Builds the real MainWindow in --self-test mode (no LAN scan,
no timers) and, at the moment the self-test would quit, runs one scenario's
checks against the live widgets, then prints one ``CHECK|scenario|name|PASS|FAIL|detail``
line per check. The browser launcher is patched, so nothing external ever opens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import accent  # noqa: E402
import cast_targets  # noqa: E402
import castctl  # noqa: E402
import cast_control  # noqa: E402
import streamer  # noqa: E402
import version  # noqa: E402
import video_policy  # noqa: E402
from gi.repository import Gio, GLib, Gtk  # noqa: E402

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else ""
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))


def pump(seconds: float) -> None:
    """Let queued GTK idle callbacks and background workers deliver their results."""
    context = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + int(seconds * 1_000_000)
    while GLib.get_monotonic_time() < end:
        while context.pending():
            context.iteration(False)
        GLib.usleep(10_000)


def menu_items(model) -> list[tuple[str, str]]:
    """Every (label, action) in a Gio.MenuModel, descending into sections and submenus."""
    found: list[tuple[str, str]] = []
    for index in range(model.get_n_items()):
        label = model.get_item_attribute_value(index, "label", None)
        action = model.get_item_attribute_value(index, "action", None)
        if action is not None:
            found.append((label.get_string() if label else "", action.get_string()))
        for link in ("section", "submenu"):
            child = model.get_item_link(index, link)
            if child is not None:
                found.extend(menu_items(child))
    return found


def dropdown_names(dropdown) -> list[str]:
    model = dropdown.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())] if model is not None else []


# --- scenarios ------------------------------------------------------------------

def first_run(app, window) -> None:
    """No saved receiver: nothing selected, nothing commanded, user is asked to choose (#239)."""
    for button, label in ((window.open_button, "Open video"), (window.cast_button, "Cast to TV"),
                          (window.stop_tv_button, "Stop TV")):
        check(f"player action displays {label}", button.get_label() == label)

    calls: list[list[str]] = []

    def record(args, timeout=10):  # a catt subprocess would be spawned through this
        calls.append(list(args))
        raise OSError("no receiver should be contacted on first run")

    castctl._run = record
    check("config has no device", window.cfg.get("device") == "", repr(window.cfg.get("device")))
    check("_device() is empty", window._device() == "")
    check("dropdown starts with the placeholder only",
          dropdown_names(window.device_dropdown) == [cast_targets.CHOOSE_RECEIVER],
          repr(dropdown_names(window.device_dropdown)))
    window._poll_device()
    window.volume_scale.set_value(30)
    pump(1.0)
    check("polling and volume never run catt without a receiver", calls == [], repr(calls))

    kitchen = castctl.Device(name="Kitchen", host="192.168.1.60", uuid="uuid-kitchen")
    window._scan_done(([kitchen], []))
    pump(0.3)
    check("scan lists the receiver after the placeholder",
          dropdown_names(window.device_dropdown) == [cast_targets.CHOOSE_RECEIVER, "Kitchen"],
          repr(dropdown_names(window.device_dropdown)))
    check("scan does not choose one for the user: the placeholder stays selected, nothing is saved",
          window.device_dropdown.get_selected() == 0 and window.cfg.get("device") == "",
          f"selected={window.device_dropdown.get_selected()} device={window.cfg.get('device')!r}")
    text = window.device_detail.get_text()
    check("the user is asked to choose a receiver", "choose" in text.lower(), repr(text))
    check("still no catt command after the scan", calls == [], repr(calls))

    window.device_dropdown.set_selected(1)                      # the user picks Kitchen
    pump(0.5)
    check("picking a receiver saves it", window.cfg.get("device") == "Kitchen", repr(window.cfg.get("device")))
    check("only now is the chosen receiver contacted",
          any("Kitchen" in call for call in calls) and all("Kitchen" in " ".join(c) for c in calls if "-d" in c),
          repr(calls))


def saved_device(app, window) -> None:
    """An existing user's saved receiver is untouched by the first-run change (#239)."""
    check("saved device is kept", window.cfg.get("device") == "Seeded TV", repr(window.cfg.get("device")))
    check("dropdown shows the saved device", dropdown_names(window.device_dropdown) == ["Seeded TV"],
          repr(dropdown_names(window.device_dropdown)))
    check("saved device is selected", window.device_dropdown.get_selected() == 0,
          str(window.device_dropdown.get_selected()))


def report_problem(app, window) -> None:
    """Help > Report a problem opens a prefilled bug form and sends nothing itself (#274)."""
    items = menu_items(window.menu_button.get_menu_model())
    check("menu has the entry", ("Report a problem…", "app.report-problem") in items,
          repr([i for i in items if "problem" in i[0].lower()]))
    action = app.lookup_action("report-problem")
    check("the app action is registered", action is not None)
    opened: list[str] = []
    toasts: list[tuple[str, bool]] = []
    window.toast = lambda message, *, error=False: toasts.append((message, error))

    def fake_launch(uri, context=None):
        opened.append(uri)

    Gio.AppInfo.launch_default_for_uri = staticmethod(fake_launch)
    action.activate(None)
    pump(0.3)
    check("exactly one URL is opened", len(opened) == 1, repr(opened))
    if opened:
        parts = urlsplit(opened[0])
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        check("it targets the project's issue form",
              (parts.scheme, parts.netloc, parts.path) == ("https", "github.com", "/gmanldn/smoothcast/issues/new")
              and query.get("template") == "bug-report.yml", opened[0])
        check("the version is prefilled", query.get("version") == version.label(), repr(query.get("version")))
        check("the OS label has no paths or addresses",
              bool(query.get("platform")) and "/" not in query["platform"] and "192.168" not in query["platform"],
              repr(query.get("platform")))
    check("the user is told to attach the diagnostics file",
          any("diagnostics" in m.lower() and not err for m, err in toasts), repr(toasts))

    def failing_launch(uri, context=None):
        raise GLib.Error.new_literal(Gio.io_error_quark(), "no browser available", Gio.IOErrorEnum.FAILED)

    Gio.AppInfo.launch_default_for_uri = staticmethod(failing_launch)
    toasts.clear()
    action.activate(None)
    pump(0.3)
    check("a missing browser is reported as an error toast",
          any("Could not open the browser" in m and err for m, err in toasts), repr(toasts))


def picture_options(app, window) -> None:
    """Preferences > Picture: crop/deinterlace switches persist and the film preview works (#54)."""
    window.action_preferences()
    pump(0.5)
    prefs = window._preferences_window
    check("the preferences window opens with both switches",
          prefs is not None and {"auto_crop", "auto_deinterlace"} <= set(prefs._switches))
    config_file = Path(os.environ["XDG_CONFIG_HOME"]) / "cast-control" / "config.json"

    def saved() -> dict:
        return json.loads(config_file.read_text()) if config_file.exists() else {}

    check("both options start off", video_policy.load_flags() == (False, False), repr(video_policy.load_flags()))
    prefs._switches["auto_crop"].set_active(True)
    pump(0.3)
    check("turning crop on saves it and the transcoder reads it",
          saved().get("auto_crop") is True and video_policy.load_flags() == (True, False),
          f"{saved().get('auto_crop')!r} {video_policy.load_flags()}")
    prefs._switches["auto_deinterlace"].set_active(True)
    pump(0.3)
    check("turning deinterlace on saves it too", video_policy.load_flags() == (True, True), repr(video_policy.load_flags()))
    prefs._switches["auto_crop"].set_active(False)
    pump(0.3)
    check("turning crop off is reversible", video_policy.load_flags() == (False, True)
          and saved().get("auto_crop") is False, repr(saved()))

    window.media = None
    prefs.picture.button.emit("clicked")
    check("checking with no film selected says so and changes nothing",
          prefs.picture.row.get_subtitle() == "Select a film first." and prefs.picture.button.get_sensitive(),
          repr(prefs.picture.row.get_subtitle()))

    if shutil.which("ffmpeg") is None:
        check("film preview (skipped: ffmpeg is not installed)", True)
        return
    folder = Path(tempfile.mkdtemp(prefix="smoothcast-picture-"))
    clip = folder / "letterbox.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x480:rate=25:duration=6,drawbox=x=0:y=0:w=640:h=60:color=black:t=fill,"
                    "drawbox=x=0:y=420:w=640:h=60:color=black:t=fill",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-y", str(clip)],
                   check=True, capture_output=True, timeout=60)
    window.media = streamer.MediaInfo(path=clip, duration=6.0, width=640, height=480)
    prefs.sync_from_owner()
    prefs.picture.button.emit("clicked")
    check("the check shows progress and locks the button while it runs",
          prefs.picture.row.get_subtitle().startswith("Checking") and not prefs.picture.button.get_sensitive())
    for _ in range(300):
        pump(0.1)
        if prefs.picture.button.get_sensitive():
            break
    text = prefs.picture.row.get_subtitle()
    check("the preview reports the black bars that would be cropped",
          text.startswith("Black bars: crop to 640\u00d7360") and "removes 25%" in text, repr(text))
    check("the preview reports the film as progressive", "Progressive" in text, repr(text))
    check("the button is usable again", prefs.picture.button.get_sensitive())

    prefs.picture.button.emit("clicked")
    window.media = None                                         # the user picks another film mid-check
    for _ in range(300):
        pump(0.1)
        if prefs.picture.button.get_sensitive():
            break
    check("changing film during a check never leaves the row stuck",
          prefs.picture.button.get_sensitive() and "Checking" not in prefs.picture.row.get_subtitle(),
          repr(prefs.picture.row.get_subtitle()))
    shutil.rmtree(folder, ignore_errors=True)


def accent_choice(app, window) -> None:
    """Preferences > Appearance > Accent colour: bounded presets, live, reversible, no theme edits (#135)."""
    errors: list[str] = []
    for preset_id, _label, _hex in accent.PRESETS:
        provider = Gtk.CssProvider()
        provider.connect("parsing-error", lambda _p, _section, error: errors.append(error.message))
        provider.load_from_data(accent.css_for(preset_id) or "window { }")
    check("every preset's CSS parses in real GTK without errors", errors == [], repr(errors))

    window.action_preferences()
    pump(0.5)
    prefs = window._preferences_window
    combo = prefs._combos.get("accent")
    check("the Accent colour choice exists with one entry per preset",
          combo is not None and combo.get_model().get_n_items() == len(accent.PRESETS))
    config_file = Path(os.environ["XDG_CONFIG_HOME"]) / "cast-control" / "config.json"

    def saved() -> dict:
        return json.loads(config_file.read_text()) if config_file.exists() else {}

    # A probe label that takes the accent through the stylesheet: .queue-row.current .queue-title
    probe_window = Gtk.Window()
    row = Gtk.Box()
    row.add_css_class("queue-row")
    row.add_css_class("current")
    label = Gtk.Label(label="probe")
    label.add_css_class("queue-title")
    row.append(label)
    probe_window.set_child(row)
    probe_window.present()
    pump(0.4)

    def colour() -> tuple[int, int, int]:
        c = label.get_color()
        return round(c.red * 255), round(c.green * 255), round(c.blue * 255)

    def expected(preset_id: str) -> tuple[int, int, int]:
        hover = accent.mix(accent.accent_hex(preset_id), accent.LIGHT_TEXT, 0.18)
        return int(hover[1:3], 16), int(hover[3:5], 16), int(hover[5:7], 16)

    original = colour()   # whatever the stylesheet's own colour is today (it has changed before)
    check("default: no override is installed and Default is selected",
          app._accent_provider is None and combo.get_selected() == 0, f"{original}")
    check("an accent is detectable: the default differs from every preset's colour",
          all(expected(p) != original for p, _l, _h in accent.PRESETS if p != accent.DEFAULT_ID), f"{original}")
    for preset_id in ("amber", "violet", "teal"):
        index = [p for p, _l, _h in accent.PRESETS].index(preset_id)
        combo.set_selected(index)
        pump(0.5)
        check(f"{preset_id}: applied live through the stylesheet", colour() == expected(preset_id),
              f"{colour()} != {expected(preset_id)}")
        check(f"{preset_id}: saved to config.json", window.cfg["accent"] == preset_id
              and saved().get("accent") == preset_id, repr(saved().get("accent")))
    check("switching presets replaces the override instead of stacking providers",
          app._accent_provider is not None and colour() == expected("teal"))
    combo.set_selected(0)
    pump(0.5)
    check("Default removes the override and restores the original colour",
          app._accent_provider is None and colour() == original, f"{colour()}")
    check("Default is saved too", saved().get("accent") == "default", repr(saved().get("accent")))
    check("the GTK theme setting is untouched",
          "theme" not in json.dumps(saved()).lower().replace("auto_theme", ""))
    probe_window.destroy()


def accent_saved(app, window) -> None:
    """An accent saved in an earlier session is applied at startup, and junk values are ignored (#135)."""
    probe_window = Gtk.Window()
    row = Gtk.Box()
    row.add_css_class("queue-row")
    row.add_css_class("current")
    label = Gtk.Label(label="probe")
    label.add_css_class("queue-title")
    row.append(label)
    probe_window.set_child(row)
    probe_window.present()
    pump(0.4)
    c = label.get_color()
    hover = accent.mix(accent.accent_hex("violet"), accent.LIGHT_TEXT, 0.18)
    want = (int(hover[1:3], 16), int(hover[3:5], 16), int(hover[5:7], 16))
    got = (round(c.red * 255), round(c.green * 255), round(c.blue * 255))
    check("the saved accent is applied at startup", app._accent_provider is not None and got == want,
          f"{got} != {want}")
    check("the window's setting matches", window.cfg.get("accent") == "violet", repr(window.cfg.get("accent")))
    window.action_preferences()
    pump(0.4)
    check("Preferences shows the saved accent as selected",
          window._preferences_window._combos["accent"].get_selected()
          == [p for p, _l, _h in accent.PRESETS].index("violet"),
          str(window._preferences_window._combos["accent"].get_selected()))
    probe_window.destroy()


def accent_junk(app, window) -> None:
    """A corrupt accent value in config.json is ignored: default look, no crash (#135)."""
    check("a junk accent falls back to the default", window.cfg.get("accent") == "default"
          and app._accent_provider is None, repr(window.cfg.get("accent")))


def _narrow_helpers(window):
    """Helpers that put the window's layout logic into a real 360 px state and measure it."""
    window.get_width = lambda: 360          # exactly what the reflow code reads in a 360 px window
    window.get_height = lambda: 800

    def settle() -> None:
        for _ in range(4):                  # the 200 ms reflow timer does not run in self-test mode
            window._refresh_responsive_layout()
            pump(0.4)

    def minwidth() -> int:
        return window.measure(Gtk.Orientation.HORIZONTAL, -1)[0]

    def find(css_class: str):
        stack = [window]
        while stack:
            widget = stack.pop()
            if css_class in widget.get_css_classes():
                return widget
            child = widget.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()
        return None

    return settle, minwidth, find


def density_choice(app, window) -> None:
    """Interface density: live, saved, scales spacing/controls, never clips at 360 px or large fonts (#136)."""
    import density
    window.action_preferences()
    pump(0.5)
    prefs = window._preferences_window
    combo = prefs._combos.get("density")
    check("the Interface density choice has one entry per preset",
          combo is not None and combo.get_model().get_n_items() == len(density.PRESETS))
    config_file = Path(os.environ["XDG_CONFIG_HOME"]) / "cast-control" / "config.json"

    def saved() -> dict:
        return json.loads(config_file.read_text()) if config_file.exists() else {}

    settle, minwidth, find = _narrow_helpers(window)
    settle()
    ids = [p for p, _l, _s in density.PRESETS]
    measured: dict[str, dict[str, int]] = {}
    for name in ("compact", "comfortable", "spacious"):
        combo.set_selected(ids.index(name))
        pump(0.4)
        settle()
        big_play, card = find("big-play"), find("hero-card")
        measured[name] = {
            "margin": window.page.get_margin_start(),
            "big_play": big_play.measure(Gtk.Orientation.HORIZONTAL, -1)[0],
            "card_height": card.measure(Gtk.Orientation.VERTICAL, 340)[0],
        }
        check(f"{name}: saved to config.json and applied",
              window.cfg["density"] == name and saved().get("density") == name
              and (app._density_provider is None) == (name == "comfortable"), repr(saved().get("density")))
        check(f"{name}: the 360 px layout is not wider than 360 px", minwidth() <= 360, f"min={minwidth()}")
    for key in ("margin", "big_play", "card_height"):
        a, b, c = (measured[n][key] for n in ("compact", "comfortable", "spacious"))
        check(f"spacing scales with density: {key} compact < comfortable < spacious", a < b < c,
              f"{a} / {b} / {c}")
    check("the big-play control matches the scaled stylesheet value",
          measured["spacious"]["big_play"] == density.px(density.BASE_COMPACT["big_play"], 1.25)
          and measured["compact"]["big_play"] == density.px(density.BASE_COMPACT["big_play"], 0.85),
          repr({k: v["big_play"] for k, v in measured.items()}))

    settings = Gtk.Settings.get_default()
    for font in ("Sans 14", "Sans 18", "Sans 22"):
        settings.set_property("gtk-font-name", font)
        for name in ("compact", "comfortable", "spacious"):
            combo.set_selected(ids.index(name))
            pump(0.3)
            settle()
            check(f"{font} / {name}: still not wider than 360 px", minwidth() <= 360, f"min={minwidth()}")
    combo.set_selected(ids.index("comfortable"))
    pump(0.4)
    check("back to comfortable: the override is gone and it is saved",
          app._density_provider is None and saved().get("density") == "comfortable")


def density_saved(app, window) -> None:
    """A saved density applies at startup and shows as selected (#136)."""
    import density
    settle, _minwidth, _find = _narrow_helpers(window)
    settle()
    check("the saved density is applied at startup", app._density_provider is not None
          and window.cfg.get("density") == "spacious", repr(window.cfg.get("density")))
    check("the layout uses the spacious scale", window.page.get_margin_start() == density.px(8, 1.25, 4),
          str(window.page.get_margin_start()))
    window.action_preferences()
    pump(0.4)
    check("Preferences shows it as selected",
          window._preferences_window._combos["density"].get_selected() == 2,
          str(window._preferences_window._combos["density"].get_selected()))


def density_junk(app, window) -> None:
    """A corrupt density value is ignored: normal look, no crash (#136)."""
    check("a junk density falls back to comfortable", window.cfg.get("density") == "comfortable"
          and app._density_provider is None, repr(window.cfg.get("density")))


def text_fit_wide(app, window) -> None:
    """The text-fit pass is narrow-only: a wide window keeps its labels exactly as designed (#136)."""
    import text_fit
    window.get_width = lambda: text_fit.NARROW_WIDTH + 200      # a wide window, from the very first reflow
    window.get_height = lambda: 900
    for _ in range(3):
        window._refresh_responsive_layout()
        pump(0.3)
    changed = text_fit.fit_labels(window)
    check("a wide window's reflow left every label as designed (there is still work for the pass to do)",
          changed > 0, str(changed))
    check("fitting is idempotent", text_fit.fit_labels(window) == 0)
    window.get_width = lambda: 360                              # now narrow: nothing new to change, and it stays that way
    window._refresh_responsive_layout()
    pump(0.3)
    check("a narrow reflow afterwards changes nothing more", text_fit.fit_labels(window) == 0)


def audio_delay_menu(app, window) -> None:
    """The real app actions move, save and reset a per-film audio delay (#113)."""
    config_file = Path(os.environ["XDG_CONFIG_HOME"]) / "cast-control" / "config.json"

    def saved() -> dict:
        return json.loads(config_file.read_text()).get("audio_delay_by_file", {}) if config_file.exists() else {}

    def press(name: str) -> None:
        action = app.lookup_action(name)
        action.activate(None)
        pump(0.2)

    actions = ("audio-earlier", "audio-later", "audio-reset")
    check("the three audio-delay actions exist and are enabled",
          all(app.lookup_action(n) is not None and app.lookup_action(n).get_enabled() for n in actions))
    press("audio-later")
    check("with no film open nothing is saved", saved() == {} and window.cfg.get("audio_delay_by_file", {}) == {})
    film = "/tmp/smoothcast-gui-check-film.mkv"
    window._preview_path = film
    press("audio-later")
    press("audio-later")
    check("two presses of 'later' save +100 ms for that film only", saved() == {film: 100}, repr(saved()))
    press("audio-earlier")
    check("'earlier' moves it back by 50 ms", saved() == {film: 50}, repr(saved()))
    press("audio-reset")
    check("reset clears the saved delay", saved() == {}, repr(saved()))
    for _ in range(3):
        press("audio-earlier")
    check("earlier goes negative and is saved", saved() == {film: -150}, repr(saved()))
    window._preview_path = "/tmp/another-film.mkv"
    check("another film starts with no delay", window.cfg["audio_delay_by_file"].get(window._preview_path) is None)


SCENARIOS = {"first-run": first_run, "saved-device": saved_device, "report-problem": report_problem,
             "picture-options": picture_options, "accent": accent_choice,
             "accent-saved": accent_saved, "accent-junk": accent_junk,
             "density": density_choice, "density-saved": density_saved,
             "density-junk": density_junk, "text-fit": text_fit_wide,
             "audio-delay": audio_delay_menu}


class CheckApp(cast_control.CastControlApp):
    def _selftest_quit(self) -> bool:
        try:
            SCENARIOS[SCENARIO](self, self.window)
        except Exception:
            check("scenario ran without an exception", False, traceback.format_exc().strip().splitlines()[-1])
        for name, ok, detail in RESULTS:
            print(f"CHECK|{SCENARIO}|{name}|{'PASS' if ok else 'FAIL'}|{detail}", flush=True)
        self.selftest_failed = not all(ok for _n, ok, _d in RESULTS) or not RESULTS
        self.quit()
        return False


def main() -> int:
    if SCENARIO not in SCENARIOS:
        print(f"unknown scenario {SCENARIO!r}", file=sys.stderr)
        return 2
    app = CheckApp(selftest=True)
    app.run([sys.argv[0]])
    return 1 if app.selftest_failed else 0


if __name__ == "__main__":
    sys.exit(main())
