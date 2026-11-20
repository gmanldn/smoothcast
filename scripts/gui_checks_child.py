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

import cast_targets  # noqa: E402
import castctl  # noqa: E402
import cast_control  # noqa: E402
import streamer  # noqa: E402
import version  # noqa: E402
import video_policy  # noqa: E402
from gi.repository import Gio, GLib  # noqa: E402

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


SCENARIOS = {"first-run": first_run, "saved-device": saved_device, "report-problem": report_problem,
             "picture-options": picture_options}


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
