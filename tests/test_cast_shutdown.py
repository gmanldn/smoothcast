"""Headless lifecycle tests: no GTK display or receiver is launched."""
from __future__ import annotations

import textwrap
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from entry_name import EntryName
from gui_source import main_window_methods
from portal import Portal
import reliability_metrics
import shutdown_plan

METHODS = main_window_methods()


def lifecycle_type():
    """Execute only extracted lifecycle methods against a test double."""
    names = ("_on_close", "_finish_delayed_close", "_stop_portal", "_stop_sc_core")
    code = "class Lifecycle:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(METHODS[name]), "    ") for name in names
    )
    namespace = {
        "threading": threading, "time": time, "save_config": lambda _: None,
        "flush_config": lambda: True,
        "reliability_metrics": reliability_metrics, "Async": mock.Mock(),
        "peer_discovery_ui": mock.Mock(),
    }
    exec(compile(code, "<lifecycle-test>", "exec"), namespace)
    return namespace["Lifecycle"]


class FakeApp:
    def __init__(self):
        self.holds = 0
        self.releases = 0

    def hold(self):
        self.holds += 1

    def release(self):
        self.releases += 1


def window(*, keep=False, mode="transcode"):
    class FakeWindow(lifecycle_type()):
        def _stop_ui_timers(self):
            pass

        def _shutdown_plan(self):
            if not hasattr(self, "plan"):
                self.plan = shutdown_plan.ShutdownPlan()
            return self.plan

        def _finish_shutdown(self):
            self.finished = getattr(self, "finished", 0) + 1

        def _stop_house_services(self):
            self.house_stopped = getattr(self, "house_stopped", 0) + 1

        def __init__(self):
            self.app = FakeApp()
            self._closing = False
            self._cancel_queue_prewarm = mock.Mock()
            self._portal = None
            self._closing_hold = False
            self._cast_starting = True
            self._dlna_cancel = None
            self.cfg = {"keep_streaming": keep}
            self._last_normal_size = (1000, 700)
            self.session = None
            self.mode = mode
            self.hidden = False
            self.saved = 0
            self.stop_event = threading.Event()
            self.stop_count = 0

        def get_application(self):
            return self.app

        def set_visible(self, visible):
            self.hidden = not visible

        def _stop_monitor(self):
            self.saved += 1

        def _unload_local_video(self):
            pass

        def _remember_normal_geometry(self):
            # The headless lifecycle double stands in for the UI's allocated
            # normal-size sampler; closing a hidden window retains this size.
            self._last_normal_size = (1000, 700)


        def _device(self):
            return "Test TV"

        def close(self):
            return self._on_close(None)

    return FakeWindow()


class GuardTests(unittest.TestCase):
    def test_close_while_starting_holds_app_and_hides_window(self):
        obj = window()
        self.assertTrue(obj._on_close(None))
        self.assertTrue(obj._closing)
        self.assertTrue(obj.hidden)
        self.assertTrue(obj._closing_hold)
        self.assertEqual(obj.app.holds, 1)
        self.assertEqual(obj.app.releases, 0)
        self.assertTrue(obj._on_close(None))
        self.assertEqual(obj.app.holds, 1)  # no double hold

    def test_finished_startup_closes_once_and_stops_cast_when_keep_off(self):
        obj = window(keep=False)
        obj._on_close(None)
        fake_session = mock.Mock()
        fake_session.mode = "transcode"
        fake_session.stop.side_effect = lambda *_: obj.stop_event.set()
        obj.session = fake_session
        obj._cast_starting = False
        obj._finish_delayed_close()
        self.assertTrue(obj.stop_event.wait(2))
        self.assertEqual(obj.app.releases, 1)
        self.assertFalse(obj._closing_hold)
        fake_session.stop.assert_called_once_with("Test TV")
        self.assertEqual(obj.saved, 1)
        self.assertEqual(obj.cfg["window_width"], 1000)

    def test_keep_streaming_preserves_cast_but_never_dlna_server(self):
        for mode, stopped in (("transcode", False), ("dlna", True)):
            with self.subTest(mode=mode):
                obj = window(keep=True, mode=mode)
                obj._on_close(None)
                session = mock.Mock()
                session.mode = mode
                session.stop.side_effect = lambda *_: obj.stop_event.set()
                obj.session = session
                obj._cast_starting = False
                obj._finish_delayed_close()
                self.assertEqual(obj.app.holds, 1)
                self.assertEqual(obj.app.releases, 1)
                if stopped:
                    self.assertTrue(obj.stop_event.wait(2))
                    session.stop.assert_called_once_with("Test TV")
                else:
                    session.stop.assert_not_called()

    def test_portal_quit_overlaps_goodbyes_and_joins_worker(self):
        obj = window()
        obj._closing = True
        obj._entry_name = mock.Mock()
        obj._portal = mock.Mock()
        together = threading.Barrier(2, timeout=1)
        entry_done = threading.Event()

        def close_entry():
            together.wait()
            entry_done.set()

        obj._entry_name.close.side_effect = close_entry
        obj._portal.stop.side_effect = together.wait
        with mock.patch("cast_mesh.stop"):
            obj._stop_portal()
        self.assertTrue(entry_done.is_set())
        self.assertIsNone(obj._entry_name)
        self.assertIsNone(obj._portal)

    def test_portal_quit_completes_two_250_ms_goodbyes_within_350_ms(self):
        entry_zeroconf, portal_zeroconf = mock.Mock(), mock.Mock()
        for zeroconf in (entry_zeroconf, portal_zeroconf):
            zeroconf.unregister_service.side_effect = lambda _info: time.sleep(0.25)

        entry = EntryName("127.0.0.1", 12345,
                          zeroconf_factory=lambda _ip: entry_zeroconf,
                          info_factory=mock.Mock())
        entry.apply(True)
        portal = Portal.__new__(Portal)
        portal.peers = None
        portal._zeroconf, portal._service_info = portal_zeroconf, object()
        portal.thread = SimpleNamespace(is_alive=lambda: True, join=mock.Mock())
        portal.server = mock.Mock(uploads=None)
        obj = window()
        obj._closing = True
        obj._entry_name, obj._portal = entry, portal

        with mock.patch("cast_mesh.stop"):
            start = time.monotonic()
            obj._stop_portal()
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.35, f"Portal shutdown took {elapsed * 1000:.1f} ms")
        self.assertIsNone(entry.name)
        for zeroconf in (entry_zeroconf, portal_zeroconf):
            zeroconf.unregister_service.assert_called_once()
            zeroconf.close.assert_called_once()
        portal.server.shutdown.assert_called_once()
        portal.server.server_close.assert_called_once()

    def test_portal_rebind_closes_entry_before_stopping_server(self):
        obj = window()
        order = []
        obj._entry_name = mock.Mock()
        obj._portal = mock.Mock()
        obj._entry_name.close.side_effect = lambda: order.append("entry")
        obj._portal.stop.side_effect = lambda: order.append("portal")
        with mock.patch("cast_mesh.stop"):
            obj._stop_portal()
        self.assertEqual(order, ["entry", "portal"])

    def test_portal_quit_does_not_wait_indefinitely_for_entry(self):
        obj = window()
        obj._closing = True
        obj._entry_name = mock.Mock()
        obj._portal = mock.Mock()
        release = threading.Event()
        finished = threading.Event()

        def close_entry():
            try:
                release.wait(3)
            finally:
                finished.set()

        obj._entry_name.close.side_effect = close_entry
        started = time.monotonic()
        try:
            with mock.patch("cast_mesh.stop"), mock.patch("builtins.print") as log:
                obj._stop_portal()
            self.assertLess(time.monotonic() - started, 1.0)
            log.assert_any_call("SmoothCast entry-name shutdown timed out", flush=True)
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_cast_startup_clears_guard_in_both_callbacks(self):
        cast = METHODS["_cast_path"]
        self.assertIn("self._cast_starting = True", cast)
        self.assertIn("self._cast_starting = False", cast)
        self.assertIn("self._finish_delayed_close()", cast)
        self.assertIn('raise streamer.StreamError("Cast cancelled because SmoothCast is closing")', cast)
        self.assertLess(cast.index("self._cast_starting = True"),
                        cast.index('Async.run(work, done=done, failed=failed, domain="cast_start")'))


if __name__ == "__main__":
    unittest.main()
