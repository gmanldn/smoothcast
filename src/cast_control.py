#!/usr/bin/env python3
"""Cast Control — modern Chromecast companion."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
import os

from position_tracker import PositionTracker
import pathlib

import sys

from position_tracker import PositionTracker
import threading

import castctl

import diagnostics

import dlna

import streamer

import smoothcast_assets

import stream_watchdog

import audio_monitor

import responsive_layout

import gui_test_safety

import update_control

import version

import error_log

import local_playback

import startup_cleanup

from cast_widgets import APP_ID, APP_NAME, ICON_NAME, CSS, load_config, save_config, LevelMeter, PreviewScreen
from cast_ui import UiMixin
from cast_queue import QueueMixin
from cast_session import SessionMixin
from cast_av import AvMixin
from cast_lifecycle import LifecycleMixin


class MainWindow(UiMixin, QueueMixin, SessionMixin, AvMixin, LifecycleMixin, Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self.app = app
        self.cfg = load_config()
        self.session: streamer.Session | None = None
        self.media: streamer.MediaInfo | None = None
        self.device_info: dict | None = None
        self.devices: list[castctl.Device] = []
        self.dlna_devices: list[dlna.Renderer] = []
        self._dlna_by_key: dict[str, dlna.Renderer] = {}
        self.device_state = "IDLE"
        self.external = False
        # A remote URL cast has no local Session. Remember the exact URL we sent
        # so the sleep timer can stop our own stream but never a replacement.
        self._url_cast_url: str | None = None
        self._url_cast_seen = False
        self.busy = False
        self._dlna_cancel: threading.Event | None = None
        self.poll_busy = False
        self.scan_busy = False
        self._scan_again = False
        self.queue: list[str] = []
        self.queue_durations: dict[str, float] = {}
        self.now_playing: str | None = None
        self.selected_index: int | None = None
        self.tracker = PositionTracker()
        self._stream_watchdog = stream_watchdog.StreamWatchdog()
        self._volume_job: int | None = None
        self._volume_target: str | None = None
        self._volume_user_ts = 0.0
        self._syncing = False
        self._subs_cache: tuple[str, str | None] = ("", None)
        self._hover_time: float | None = None
        self._finished_handled = False
        self._closing = False
        self._cast_starting = False
        self._closing_hold = False
        self._last_state = "IDLE"
        self._play_icon_name = "media-playback-start-symbolic"
        self.meter: LevelMeter | None = None
        self.master_meter: MasterMeter | None = None
        self.preview: PreviewScreen | None = None
        self.monitor: audio_monitor.AudioMonitor | None = None
        self._mon_path: pathlib.Path | None = None
        self._mon_chain: list[str] = []
        self.console_lines: list[str] = []
        self.update_notice: str | None = None
        self.local_playback = local_playback.LocalPlayback()
        # Pre-cast previews are independent of the Chromecast playback clock.
        self._preview_path: str | None = None
        self._preview_position = 0.0
        self._preview_generation = 0
        self._preview_pending: tuple[str, float, int] | None = None
        self._preview_busy = False
        self._preview_timer_id = 0
        self._local_video_path: str | None = None
        self._local_start_pending: float | None = None
        self._media_cache: dict[str, tuple[tuple[int, int], streamer.MediaInfo]] = {}
        self._preflight_ok: set[tuple] = set()  # successful source/caption fingerprints

        # GTK4/Wayland controls window placement; avoid the removed Gtk3
        # move()/get_position() APIs and never force a fullscreen-sized minimum.
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        monitor = monitors.get_item(0) if monitors and monitors.get_n_items() else None
        geometry = monitor.get_geometry() if monitor else None
        self._startup_width, self._startup_height = responsive_layout.window_size(
            self.cfg.get("window_width"), self.cfg.get("window_height"),
            geometry.width if geometry else None,
            geometry.height if geometry else None,
        )
        self.set_default_size(self._startup_width, self._startup_height)
        self._last_normal_size = (self._startup_width, self._startup_height)
        self.set_size_request(360, 320)
        self._layout_state = None
        self._build_ui()
        self._refresh_responsive_layout()
        self._flush_stale_state()
        self._refresh_direct_note()
        self.connect("close-request", self._on_close)
        self._install_shortcuts()
        self._apply_color_scheme()
        self._refresh_controls()
        if not app.selftest:
            # A GUI smoke test builds widgets only: it must not scan LANs,
            # adopt casts, poll receivers or run media/telemetry timers.
            GLib.timeout_add(500, self._tick)
            GLib.timeout_add(200, self._refresh_responsive_layout)
            GLib.timeout_add(100, self._meter_tick)
            GLib.timeout_add(900, lambda: (self._poll_device(), False)[1])
            GLib.timeout_add(4000, self._poll_device)
            GLib.timeout_add(400, self._initial_scan)
            GLib.timeout_add(600, self._adopt_session)
            GLib.timeout_add_seconds(5, self._sleep_tick)
            GLib.timeout_add_seconds(600, self._theme_tick)


"""Cast Control — modern Chromecast companion."""


gi.require_version("Gtk", "4.0")


gi.require_version("Adw", "1")


class CastControlApp(Adw.Application):
    def __init__(self, *, selftest: bool = False) -> None:
        if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
            raise RuntimeError("Refusing a GTK application inside pytest")
        if selftest and not gui_test_safety.is_isolated_gui_test():
            raise RuntimeError(gui_test_safety.refusal())
        flags = Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if selftest:
            # Self-tests must not activate an already-running user instance.
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.window: MainWindow | None = None
        self.selftest = selftest
        self.selftest_failed = False
        # Set when the window could not be built: this process must then end
        # instead of holding the application id with nothing on screen.
        self.fatal = False
        self._update_started = False
        self._startup_report: startup_cleanup.CleanupReport | None = None
        self._startup_reported = False
        self._pending_files: list[str] = []

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # This is executed only in the primary GApplication process, once,
        # before MainWindow and its monitor/session timers can be created.
        # Reactivating via a second dock click must NEVER stop an active cast.
        # Standalone --self-test instances must NEVER affect the user's app.
        if not self.selftest:
            try:
                self._startup_report = startup_cleanup.cleanup_before_window(
                    keep_streaming=bool(load_config().get("keep_streaming", True)),
                )
                report = self._startup_report
                if report.stopped or report.files_removed or report.temp_dirs_removed:
                    print(
                        "SmoothCast startup recovery: "
                        f"signalled {len(report.stopped)} old helper(s); "
                        f"removed {report.files_removed} stale stream file(s), "
                        f"{report.temp_dirs_removed} old meter directory/directories"
                    )
                for warning in report.errors:
                    print(f"SmoothCast startup recovery: {warning}", file=sys.stderr)
            except Exception as exc:
                # A cleanup failure must not prevent opening the application.
                print(f"SmoothCast startup recovery failed: {exc}", file=sys.stderr)
        GLib.set_prgname(APP_ID)
        Gtk.Window.set_default_icon_name(ICON_NAME)
        # The icon must resolve from a built wheel, never depend on an
        # adjacent Git checkout's data/ directory.
        _icon = smoothcast_assets.icon_path()
        try:
            if _icon.is_file():
                Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(
                    str(_icon.parent)
                )
        except Exception:
            pass
        error_log.install_excepthook()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._register_actions()
        self.set_accels_for_action("app.open", ["<Control>o"])
        self.set_accels_for_action("app.add-files", ["<Control>a"])
        self.set_accels_for_action("app.shortcuts", ["<Control>question"])
        self.set_accels_for_action("app.stop-stream", ["<Control>w"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _register_actions(self) -> None:
        def simple(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        simple("open", lambda *a: self._window().action_open())
        simple("play-locally", lambda *a: self._window()._play_locally())
        simple("add-files", lambda *a: self._window().action_add_files())
        simple("stop-stream", lambda *a: self._window().action_stop())
        simple("fullscreen", lambda *a: self._window()._toggle_fullscreen())
        simple("loop", lambda *a: self._window()._toggle_loop())
        simple("custom-speed", lambda *a: self._window().action_custom_speed())
        simple("loop-all", lambda *a: self._window()._toggle_loop_all())
        simple("shuffle-queue", lambda *a: self._window()._shuffle_queue())
        simple("save-playlist", lambda *a: self._window()._save_playlist())
        simple("load-playlist", lambda *a: self._window()._load_playlist())
        simple("theater", lambda *a: self._window()._toggle_theater())
        simple("auto-shutdown", lambda *a: self._window()._toggle_auto_shutdown())
        simple("auto-theme", lambda *a: self._window()._toggle_auto_theme())
        for s in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            simple(f"speed-{str(s).replace('.','_')}", lambda *a, sp=s: self._window()._set_speed(sp))
        for m in (0, 15, 30, 45, 60):
            simple(f"sleep-{m}", lambda *a, mm=m: self._window()._sleep_timer(mm))
        simple("shortcuts", lambda *a: self._window().action_shortcuts())
        simple("save-diagnostics", lambda *a: self._window().action_save_diagnostics())
        simple("open-url", lambda *a: self._window()._open_url())
        simple("screenshot", lambda *a: self._window()._screenshot())
        simple("clear-recents", lambda *a: self._window()._clear_recents())
        simple("favourite", lambda *a: self._window()._toggle_favourite())
        simple("clear-favourites", lambda *a: self._window()._clear_favourites())
        simple("about", lambda *a: self._window().action_about())
        simple("quit", lambda *a: self._window().close())
        for index in range(8):
            action = Gio.SimpleAction.new(f"recent-{index}", None)
            action.connect("activate", lambda _a, _p, i=index: self._window().open_recent(i))
            self.add_action(action)
        for index in range(16):
            action = Gio.SimpleAction.new(f"favourite-{index}", None)
            action.connect("activate", lambda _a, _p, i=index: self._window()._open_favourite(i))
            self.add_action(action)
        scheme = Gio.SimpleAction.new_stateful(
            "color-scheme", GLib.VariantType.new("s"), GLib.Variant("s", "prefer-dark")
        )
        scheme.connect("activate", self._activate_scheme)
        self.add_action(scheme)
        self.scheme_action = scheme

    def _activate_scheme(self, action, parameter) -> None:
        value = parameter.get_string()
        action.set_state(GLib.Variant("s", value))
        window = self.window
        if window is not None:
            window.cfg["color_scheme"] = value
            # An explicit choice overrides the time-based schedule.
            window.cfg["auto_theme"] = False
            save_config(window.cfg)
            window._apply_color_scheme()

    def _window(self) -> MainWindow:
        window = self.window
        if window is None:
            try:
                window = MainWindow(self)
            except Exception as exc:
                # A window that cannot be built must never leave this process as
                # a windowless D-Bus primary: every later launch would forward
                # here and show nothing. Fail loudly and release the app id.
                self.fatal = True
                print(f"{APP_NAME} could not build its window: {exc}", file=sys.stderr)
                GLib.idle_add(self._quit_fatal)
                raise
            self.window = window
            self.scheme_action.set_state(GLib.Variant("s", window.cfg["color_scheme"]))
        return window


    def _quit_fatal(self) -> bool:
        """End a process whose window failed so the next launch can take over."""
        self.quit()
        return False


    def do_activate(self) -> None:
        window = self._window()
        window.present()
        if not self._startup_reported:
            self._startup_reported = True
            report = self._startup_report
            if report is not None:
                if report.stopped:
                    window.toast(f"Recovered {len(report.stopped)} old SmoothCast helper(s)")
                if report.stopped or report.files_removed or report.temp_dirs_removed:
                    window._console(
                        f"Startup recovery: {len(report.stopped)} old helper(s) signalled, "
                        f"{report.files_removed} stream file(s) and "
                        f"{report.temp_dirs_removed} meter directory/directories removed"
                    )
                for warning in report.errors:
                    window._console(f"Startup recovery warning: {warning}")
        if self._pending_files:
            window.open_paths(self._pending_files)
            self._pending_files = []
        if self.selftest:
            # The only permitted self-test display is the disposable Xvfb
            # session. Exit promptly and avoid persistent user state.
            GLib.timeout_add(1500, self._selftest_quit)
        elif not self._update_started:
            self._update_started = True
            # Never delay the first window while DNS/network/git is unresponsive.
            threading.Thread(
                target=self._background_update,
                name="smoothcast-git-update",
                daemon=False,
            ).start()

    def _background_update(self) -> None:
        notice = update_control.refresh_checkout(
            pathlib.Path(__file__).resolve().parent.parent,
        )
        if notice:
            # All GTK work stays on the main loop; the version displayed in
            # the title remains the imported *running* release until restart.
            GLib.idle_add(self._present_update_notice, notice)

    def _present_update_notice(self, notice: str) -> bool:
        window = self.window
        if window is not None:
            window.update_notice = notice
            window._update_header_subtitle()
            window._console(notice)
            window.toast(notice)
        return False

    def _selftest_quit(self) -> bool:
        try:
            print("SELFTEST: window built successfully")
        except Exception as exc:  # pragma: no cover - defensive
            self.selftest_failed = True
            print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        finally:
            # A broken completion probe must never hang --self-test: always
            # leave the main loop so the runner's deadline is not the only
            # thing that can end it.
            self.quit()
        return False

    def do_open(self, files, n_files, _hint) -> None:
        paths = []
        for index in range(n_files):
            path = files[index].get_path()
            if path:
                paths.append(path)
        window = self._window()
        window.present()
        if paths:
            window.open_paths(paths)


    def do_command_line(self, command_line) -> int:
        raw = command_line.get_arguments()[1:]
        # For GApplication's forwarded command lines, get_cwd() refers to
        # the invoking process, not the already-running GUI. Using Path.cwd()
        # here could open a same-named decoy file from the checkout.
        caller = command_line.get_cwd()
        caller_dir = pathlib.Path(os.fsdecode(caller)) if caller else pathlib.Path.cwd()
        action = None
        paths: list[str] = []
        index = 0
        while index < len(raw):
            argument = raw[index]
            if argument == "--action" and index + 1 < len(raw):
                action = raw[index + 1]
                index += 2
                continue
            if argument.startswith("file://"):
                path = GLib.filename_from_uri(argument)[0]
                if path:
                    paths.append(path)
            elif argument and not argument.startswith("-"):
                try:
                    candidate = pathlib.Path(argument).expanduser()
                    if not candidate.is_absolute():
                        candidate = caller_dir / candidate
                    if candidate.is_file():
                        paths.append(str(candidate.resolve()))
                except (OSError, RuntimeError, ValueError):
                    # A malformed argument must not prevent a valid neighbour
                    # from opening or cause a fallback to the checkout cwd.
                    pass
            index += 1
        self.activate()
        window = self._window()
        window.present()
        if paths:
            window.open_paths(paths)
        if action:
            GLib.timeout_add(250, lambda: (window.perform_action(action), False)[1])
        return 0


def main() -> int:
    if sys.argv[1:] in (["--version"], ["-V"]):
        print(f"{APP_NAME} {version.label()}")
        return 0
    if sys.argv[1:2] == ["--diagnostics"]:
        # Bounded, redacted support bundle; starts no window.
        import diagnostics
        return diagnostics.main(sys.argv[2:])
    if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        print("Refusing to start GTK from pytest; run portable tests only.",
              file=sys.stderr)
        return 2
    selftest = "--self-test" in sys.argv
    if selftest and not gui_test_safety.is_isolated_gui_test():
        print(gui_test_safety.refusal(), file=sys.stderr)
        return 2
    argv = [arg for arg in sys.argv if arg != "--self-test"]

    # GTK startup is never delayed by a network-based git pull.
    # The first visible window schedules a non-blocking update check.
    # GTK/GApplication handles single-instance D-Bus activation: launching
    # from the dock again presents the existing window rather than exiting.

    app = CastControlApp(selftest=selftest)
    try:
        result = app.run(argv)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Cast Control error: {exc}", file=sys.stderr)
        return 1
    if app.fatal:
        # The window was never built: report failure instead of a silent,
        # windowless process that would swallow the next launch.
        print("Cast Control stopped: the window could not be built", file=sys.stderr)
        return 1
    if selftest and result == 0:
        if app.selftest_failed:
            print("SELFTEST FAILED: completion callback raised", file=sys.stderr)
            return 1
        print("SELFTEST OK")
    return result


if __name__ == "__main__":
    sys.exit(main())
