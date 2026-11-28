#!/usr/bin/env python3
"""SmoothCast desktop UI."""
from __future__ import annotations

import startup_timeline  # first: its clock starts the startup timeline (#463)
import shutdown_plan
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
import os
from position_tracker import PositionTracker
import pathlib
import settings
import sys
import threading
import accent
import castctl
import density
import sleep_fade
import dlna
import streamer
import smoothcast_assets
import stream_watchdog
import audio_monitor
import ab_repeat
import responsive_layout
import gui_test_safety
from cast_portal import PortalMixin
from cast_portal_queue import PortalQueueMixin
from join_slate_ui import JoinSlateMixin
import version
import error_log
import desktop_failure_notice
import error_banner_ui
import selftest_hold
from cast_app_lifecycle import AppLifecycleMixin
import jank_ui
import interaction_benchmark
import local_playback
import demo_mode
import startup_cleanup
from cast_widgets import APP_ID, APP_NAME, ICON_NAME, CSS, load_config, save_config, LevelMeter, PreviewScreen, Async
from cast_ui import UiMixin
from cast_settings import SettingsCardMixin
from cast_queue import QueueMixin
from cast_retry_ui import RetryController
from cast_session import SessionMixin
from cast_av import AvMixin
from cast_subtitle_files import SubtitleFileMixin
from cast_lifecycle import LifecycleMixin
from cast_ui_timers import UiTimerMixin
from find_ui import FindMixin
from cast_subtitles import SubtitleController
from cast_audio_sync import AudioSyncController
from room_checkpoint_ui import RoomCheckpointUiMixin


class MainWindow(UiMixin, SettingsCardMixin, QueueMixin, SessionMixin, AvMixin, LifecycleMixin, UiTimerMixin, FindMixin, PortalMixin, PortalQueueMixin, JoinSlateMixin, SubtitleFileMixin, RoomCheckpointUiMixin, Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self._retry = RetryController(self)
        self._subtitles = SubtitleController(self)
        self._on_burn = self._subtitles._on_burn  # bound before the settings card connects it (#691)
        self._adjust_subtitle_delay = self._subtitles._adjust_subtitle_delay
        self._adjust_audio_delay = AudioSyncController(self).adjust  # lip-sync nudge (#113, #691)
        self._retry_action = self._retry.action  # (label, callback) | None (#13, #691)
        self.app = app
        self.cfg = load_config()
        self.connect("notify::is-active", self._refresh_config_on_focus)
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
        self._sleep_fader = sleep_fade.make_fader(Async.run)
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
        self.ab_repeat = ab_repeat.ABRepeat()
        self._stream_watchdog = stream_watchdog.StreamWatchdog()
        self._volume_job: int | None = None
        self._volume_target: str | None = None
        self._volume_user_ts = 0.0
        self._syncing = False
        self._subs_cache: tuple[str, str | None] = ("", None)
        self._hover_time: float | None = None
        self._finished_handled = False
        self._closing = False
        self._timers_enabled = False
        self._timer_ids: dict[str, int] = {}
        self._timer_periods: dict[str, int | None] = {}
        self._reflow_source: int | None = None
        self._seek_idle_source: int | None = None
        self.connect("realize", self._bind_surface_resize)
        self.connect("map", self._on_mapping_change)
        self.connect("unmap", self._on_mapping_change)
        self._portal = None
        self._portal_ip: str | None = None
        self._cast_starting = False
        self._closing_hold = False
        self._last_state = "IDLE"
        self._play_icon_name = "media-playback-start-symbolic"
        self.meter: LevelMeter | None = None
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
        self._offer_room_recovery()
        self._refresh_direct_note()
        self.connect("close-request", self._on_close)
        self._install_shortcuts()
        self._apply_color_scheme()
        self._refresh_controls()


class CastControlApp(AppLifecycleMixin, jank_ui.JankMonitorMixin,
                     interaction_benchmark.InteractionBenchmarkMixin, Adw.Application):
    def __init__(self, *, selftest: bool = False) -> None:
        if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
            raise RuntimeError("Refusing a GTK application inside pytest")
        if selftest and not gui_test_safety.is_isolated_gui_test():
            raise RuntimeError(gui_test_safety.refusal())
        flags = Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if selftest or demo_mode.active():
            # Self-tests and the demo must not activate an already-running user instance.
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.window: MainWindow | None = None
        self.selftest = selftest
        self.selftest_failed = False
        # Set when the window could not be built: this process must then end
        # instead of holding the application id with nothing on screen.
        self.fatal = False
        self._startup_report: startup_cleanup.CleanupReport | None = None
        self._startup_reported = False
        self._pending_files: list[str] = []
        self._mpris = None
        self._paint_handler: int | None = None
        # Identity captured before checkout changes; never swap modules live.
        self._run_revision = version.RUNNING_REVISION
        self._noticed_runtime_key: tuple[str | None, str | None] | None = None
        self._failure_bridge: desktop_failure_notice.DesktopFailureBridge | None = None
        self.jank_monitor = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # Primary-only and before MainWindow; never stop the active user's cast.
        if not self.selftest and not demo_mode.active():
            # Demo skips recovery: it scans /proc and could stop the user's real helpers.
            shutdown_plan.begin_ledger()  # previous exit clean? (#465)
            try:
                self._startup_report = startup_cleanup.cleanup_before_window(
                    keep_streaming=bool(load_config().get("keep_streaming", True)),
                )
                report = self._startup_report
                if report.stopped or report.files_removed or report.temp_dirs_removed:
                    print(
                        "SmoothCast startup recovery: "
                        f"stopped {len(report.stopped)} old helper(s); "
                        f"removed {report.files_removed} stale stream file(s), "
                        f"{report.temp_dirs_removed} old meter directory/directories"
                    )
                for warning in report.errors:
                    print(f"SmoothCast startup recovery: {warning}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - a cleanup failure must not prevent opening the application
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
        except Exception:  # noqa: BLE001 - an icon-theme failure only loses the icon
            pass
        error_log.install_excepthook()
        # Preserve the private error log hooks, then schedule civil desktop
        # failures on the GTK main context. Never touch widgets from workers.
        self._failure_bridge = desktop_failure_notice.DesktopFailureBridge(
            schedule=GLib.idle_add, present=self._present_unexpected_failure,
            alive=self._failure_notice_available, log_glib=error_log.log,
        )
        self._failure_bridge.install_hooks()
        # Stop accepting queued work and discard callbacks after GTK exits.
        self.connect("shutdown", lambda _app: Async.shutdown())
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._accent_provider: Gtk.CssProvider | None = None
        self.apply_accent(load_config().get("accent"))
        self._density_provider: Gtk.CssProvider | None = None
        self.apply_density(load_config().get("density"))
        self._register_actions()
        self.set_accels_for_action("app.open", ["<Control>o"])
        self.set_accels_for_action("app.add-files", ["<Control>a"])
        self.set_accels_for_action("app.shortcuts", ["<Control>question"])
        self.set_accels_for_action("app.preferences", ["<Control>comma"])
        self.set_accels_for_action("app.stop-stream", ["<Control>w"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def apply_accent(self, preset) -> None:
        """Layer the accent override over the base stylesheet; the default removes it (#135)."""
        display = Gdk.Display.get_default()
        if self._accent_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._accent_provider)
            self._accent_provider = None
        css = accent.css_for(preset)
        if css:
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
            self._accent_provider = provider

    def apply_density(self, value) -> None:
        """Layer the density override over the stylesheet; comfortable removes it (#136)."""
        display = Gdk.Display.get_default()
        if self._density_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._density_provider)
            self._density_provider = None
        css = density.css_for(value)
        if css:
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2
            )
            self._density_provider = provider

    def _register_actions(self) -> None:
        def simple(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        simple("open", lambda *a: self._window().action_open())
        simple("play-locally", lambda *a: self._window()._play_locally())
        simple("add-files", lambda *a: self._window().action_add_files())
        simple("find-house", lambda *a: self._window().action_find_house())
        simple("stop-stream", lambda *a: self._window().action_stop())
        simple("fullscreen", lambda *a: self._window()._toggle_fullscreen())
        simple("loop", lambda *a: self._window()._toggle_loop())
        simple("custom-speed", lambda *a: self._window().action_custom_speed())
        simple("loop-all", lambda *a: self._window()._toggle_loop_all())
        simple("subtitle-earlier", lambda *a: self._window()._adjust_subtitle_delay(-1))
        simple("subtitle-later", lambda *a: self._window()._adjust_subtitle_delay(1))
        simple("subtitle-reset", lambda *a: self._window()._adjust_subtitle_delay(0))
        simple("audio-earlier", lambda *a: self._window()._adjust_audio_delay(-1))
        simple("audio-later", lambda *a: self._window()._adjust_audio_delay(1))
        simple("audio-reset", lambda *a: self._window()._adjust_audio_delay(0))
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
        simple("preferences", lambda *a: self._window().action_preferences())
        simple("save-diagnostics", lambda *a: self._window().action_save_diagnostics())
        simple("report-problem", lambda *a: self._window().action_report_problem())
        simple("open-url", lambda *a: self._window()._open_url())
        simple("add-youtube", lambda *a: self._window()._add_youtube())
        simple("screenshot", lambda *a: self._window()._screenshot())
        simple("benchmark", lambda *a: self._window().action_benchmark())
        simple("clear-recents", lambda *a: self._window()._clear_recents())
        simple("favourite", lambda *a: self._window()._toggle_favourite())
        simple("bookmark-add", lambda *a: self._window()._add_bookmark())
        chapter_action = Gio.SimpleAction.new("chapter-jump", GLib.VariantType.new("i"))
        chapter_action.connect("activate", lambda _action, value: self._window()._jump_to_chapter(value.get_int32()))
        self.add_action(chapter_action)
        simple("pin-receiver", lambda *a: self._window()._toggle_device_favourite())
        simple("clear-history", lambda *a: self._window()._clear_watch_history())
        simple("clear-favourites", lambda *a: self._window()._clear_favourites())
        simple("clear-bookmarks", lambda *a: self._window()._clear_bookmarks())
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
        for index in range(64):
            action = Gio.SimpleAction.new(f"bookmark-{index}", None)
            action.connect("activate", lambda _a, _p, i=index: self._window()._open_bookmark(i))
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
            except Exception as exc:  # noqa: BLE001 - report, release the app id and fail loudly
                # A window that cannot be built must never leave this process as
                # a windowless D-Bus primary: every later launch would forward
                # here and show nothing. Fail loudly and release the app id.
                self.fatal = True
                print(f"{APP_NAME} could not build its window: {exc}", file=sys.stderr)
                GLib.idle_add(self._quit_fatal)
                raise
            self.window = window
            window.connect("map", self._watch_first_paint)
            startup_timeline.mark("window_built")
            self.scheme_action.set_state(GLib.Variant("s", window.cfg["color_scheme"]))
        return window


    def _quit_fatal(self) -> bool:
        """End a process whose window failed so the next launch can take over."""
        self.quit()
        return False


    def do_activate(self) -> None:
        startup_timeline.mark("activate")
        window = self._window()
        window.present()
        self._publish_activation_ready()
        self._show_stale_runtime_notice(window)
        startup_timeline.mark("presented")
        if not self._startup_reported:
            self._startup_reported = True
            report = self._startup_report
            if report is not None:
                if report.stopped:
                    window.toast(f"Recovered {len(report.stopped)} old SmoothCast helper(s)")
                if report.stopped or report.files_removed or report.temp_dirs_removed:
                    window._console(
                        f"Startup recovery: {len(report.stopped)} old helper(s) stopped, "
                        f"{report.files_removed} stream file(s) and "
                        f"{report.temp_dirs_removed} meter directory/directories removed"
                    )
                for warning in report.errors:
                    window._console(f"Startup recovery warning: {warning}")
        if self._pending_files:
            window.open_paths(self._pending_files)
            self._pending_files = []
    def _watch_first_paint(self, window: MainWindow) -> None:
        clock = window.get_frame_clock()
        if clock is not None and self._paint_handler is None:
            self._paint_handler = clock.connect("after-paint", self._after_first_paint, window)

    def _after_first_paint(self, clock, window: MainWindow) -> None:
        clock.disconnect(self._paint_handler)
        startup_timeline.mark("first_frame")
        GLib.idle_add(self._guard_glib(self._after_paint_idle), window)

    def _after_paint_idle(self, window: MainWindow) -> bool:
        startup_timeline.mark_idle()
        self._start_jank_monitor()
        self._run_interaction_benchmark()
        import store
        if store.QUARANTINED:  # say so once instead of silently resetting a setting
            window.toast("A damaged settings file was set aside and defaults were used: "
                         + ", ".join(store.QUARANTINED[:3]), error=True)
        GLib.idle_add(self._guard_glib(self._start_optional_services), window,
                      priority=GLib.PRIORITY_LOW)
        return False

    def _start_optional_services(self, window: MainWindow) -> bool:
        if self.selftest:
            return self._selftest_quit()
        if window._closing:
            return False
        import mpris
        import sc_core

        window._start_window_timers()
        # Always-on house coordinator: keeps the mesh alive on a private LAN so
        # nodes and web clients join automatically, even from a bare ZIP run.
        sc_core.start(window)
        # Benchmark FFmpeg only after first paint, off GTK and at low priority.
        import low_end_policy
        low_end_policy.schedule_probe(enabled=bool(window.cfg.get("quality_auto", True)))
        self._mpris = mpris.start(window)
        if self._mpris is not None:
            window._sync_ui_timers()
        if (not getattr(sys, "frozen", False)
                and settings.UpdateSettings.from_config(window.cfg).check_releases):
            threading.Thread(
                target=self._background_update,
                name="smoothcast-git-update",
                daemon=True,  # read-only probe must never delay GUI shutdown
            ).start()
        return False

    def _reload_services(self) -> bool:
        """Bounce background services in place; playback is never interrupted.

        A relaunch of ``sc.py`` while SmoothCast runs reaches here so a changed
        checkout or settings take effect. Only the room, mesh, library indexer,
        heartbeat and MPRIS are restarted: the active cast, session and tracker
        are untouched, so the film keeps playing.
        """
        window = self.window
        if window is None or window._closing:
            return False
        # Before the first window timers run there is nothing to bounce; a cold
        # start has already started every service.
        if not getattr(window, "_timers_enabled", False):
            return False
        try:
            window.reload_house_services()
            window.toast("Services restarted; playback continues")
        except Exception as exc:  # a failed bounce must never disturb the session  # noqa: BLE001 - a failed service bounce must never disturb the session
            error_log.log(f"Service restart failed: {exc}")
        self._restart_mpris()
        return False


    def _background_update(self) -> None:
        cfg = getattr(self.window, "cfg", None) or {}
        from update_control import check_release

        update = settings.UpdateSettings.from_config(cfg)
        notice = check_release(
            pathlib.Path(__file__).resolve().parent.parent,
            enabled=update.check_releases,
            verify=update.verify_release,
            channel=update.channel,
        )
        if notice:
            # All GTK work stays on the main loop; the version displayed in
            # the title remains the imported *running* release until restart.
            GLib.idle_add(self._guard_glib(self._present_update_notice), notice)


    def _selftest_quit(self) -> bool:
        try:
            marks = startup_timeline.snapshot()["marks_ms"]
            if not 0 <= marks.get("first_frame", -1) <= marks.get("interactive", -1):
                raise RuntimeError("No painted, interactive window")
            print(f"SELFTEST: startup {marks}")
            print("SELFTEST: window built successfully")
            # Only the private Xvfb self-test reaches here. Prove the real
            # Adw.Toast creation works, and repeated faults do not flood it.
            bridge = self._failure_bridge
            if bridge is None:
                raise RuntimeError("desktop failure bridge not installed")
            observed = []
            original_present = bridge._present

            def checked_present(failure):
                original_present(failure)
                observed.append(failure)

            bridge._present = checked_present
            injected = RuntimeError("private /home/agent/secret.mkv")
            if not bridge.report(injected) or bridge.report(injected):
                raise RuntimeError("failure notification was not rate limited")
            # The scripted journey must not stall the main loop (#442).
            self._check_jank_gate()
            GLib.idle_add(self._finish_selftest_failures, observed)
        except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001 - self-test reports any failure and fails the run
            self.selftest_failed = True
            self._stop_jank_monitor()
            print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
            self.quit()
        return False

    def _finish_selftest_failures(self, observed) -> bool:
        try:
            if len(observed) != 1 or "private" in observed[0].message:
                raise RuntimeError("expected one civil desktop failure toast")
            print("SELFTEST: desktop failure toast was civil and rate limited")
            error_banner_ui.show_details(self.window, observed[0], retry=("Try again", lambda: None))
            print("SELFTEST: failure details dialog built")
        except Exception as exc:  # noqa: BLE001 - self-test reports any failure and fails the run
            self.selftest_failed = True
            print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        finally:
            selftest_hold.quit_when_released(self)  # bounded; quits at once by default
        return False

    def do_open(self, files, n_files, _hint) -> None:
        startup_timeline.mark("activate")
        paths = []
        for index in range(n_files):
            path = files[index].get_path()
            if path:
                paths.append(path)
        window = self._window()
        window.present()
        self._show_stale_runtime_notice(window)
        startup_timeline.mark("presented")
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
        reload_services = False
        paths: list[str] = []
        index = 0
        while index < len(raw):
            argument = raw[index]
            if argument == "--action" and index + 1 < len(raw):
                action = raw[index + 1]
                index += 2
                continue
            if argument == "--reload-services":
                # A relaunch of sc.py asks the primary to bounce its services
                # in place; playback is never interrupted (see _reload_services).
                reload_services = True
                index += 1
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
            GLib.timeout_add(250, self._guard_glib(
                lambda: (window.perform_action(action), False)[1]
            ))
        if reload_services:
            GLib.timeout_add(250, self._guard_glib(self._reload_services))
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
    except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001 - last-resort handler: report and exit non-zero
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
