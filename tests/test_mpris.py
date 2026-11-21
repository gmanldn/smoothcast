"""MPRIS2 media-player integration (issue #266); no GTK, no gi, no receiver.

Unit tests drive the service with a fake window and a fake bus. The one
integration test publishes to a private ``dbus-daemon`` inside a subprocess, so
importing this module never pulls ``gi`` into the pytest process.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mpris  # noqa: E402


class _Tracker:
    def __init__(self, position=42.0, duration=120.0, known=True, playing=True):
        self._position = position
        self.duration = duration
        self.known = known
        self.playing = playing

    def value(self):
        return self._position


class _Window:
    def __init__(self, **overrides):
        self.external = False
        self.now_playing = "/media/Film.mkv"
        self.device_state = "PLAYING"
        self.tracker = _Tracker()
        self.media = types.SimpleNamespace(duration=120.0)
        self.queue = ["/media/Film.mkv", "/media/Next.mkv"]
        self.busy = False
        self.app = None
        self.calls: list = []
        for name, value in overrides.items():
            setattr(self, name, value)

    def toggle_play(self):
        self.calls.append("toggle_play")

    def action_stop(self):
        self.calls.append("stop")

    def on_next(self):
        self.calls.append("next")

    def on_prev(self):
        self.calls.append("prev")

    def seek_to(self, target):
        self.calls.append(("seek_to", round(target, 3)))

    def present(self):
        self.calls.append("present")


class _FakeBus:
    def __init__(self):
        self.published = []
        self.emitted = []

    def publish(self, service):
        self.published.append(service)

    def emit_properties_changed(self, interface, changed):
        self.emitted.append((interface, dict(changed)))


class ImportSafetyTests(unittest.TestCase):
    def test_importing_mpris_never_imports_gi(self):
        code = ("import sys; sys.path.insert(0, %r); import mpris; "
                "assert 'gi' not in sys.modules, "
                "sorted(m for m in sys.modules if m.startswith('gi'))"
                % str(ROOT / "src"))
        env = {"PATH": os.environ.get("PATH", "")}
        result = subprocess.run([sys.executable, "-I", "-c", code],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)


class SnapshotTests(unittest.TestCase):
    def test_reports_playing_film_and_capabilities(self):
        snap = mpris.WindowAdapter(_Window()).snapshot()
        self.assertEqual(snap.playback_status, "Playing")
        self.assertEqual(snap.title, "Film")
        self.assertEqual(snap.length_us, 120_000_000)
        self.assertEqual(snap.position_us, 42_000_000)
        self.assertTrue(snap.can_play and snap.can_pause and snap.can_seek)
        self.assertTrue(snap.can_go_next)
        self.assertTrue(snap.can_go_previous)
        self.assertTrue(snap.can_control)
        self.assertEqual(snap.track_id, mpris._track_id("/media/Film.mkv"))

    def test_external_or_idle_is_stopped_and_inert(self):
        for window in (_Window(external=True), _Window(now_playing=None)):
            snap = mpris.WindowAdapter(window).snapshot()
            self.assertEqual(snap.playback_status, "Stopped")
            self.assertEqual(snap.title, "")
            self.assertFalse(any((snap.can_play, snap.can_pause, snap.can_seek,
                                  snap.can_go_next, snap.can_go_previous)))

    def test_paused_and_buffering_status(self):
        self.assertEqual(
            mpris.WindowAdapter(_Window(device_state="PAUSED")).snapshot().playback_status,
            "Paused")
        self.assertEqual(
            mpris.WindowAdapter(_Window(device_state="BUFFERING")).snapshot().playback_status,
            "Playing")

    def test_tracker_fallback_when_device_state_unknown(self):
        window = _Window(device_state="IDLE")
        window.tracker = _Tracker(known=True, playing=False)
        self.assertEqual(mpris.WindowAdapter(window).snapshot().playback_status, "Paused")

    def test_previous_always_restarts_the_track(self):
        window = _Window(now_playing="/media/Film.mkv")
        window.tracker = _Tracker(position=0.0)
        snap = mpris.WindowAdapter(window).snapshot()
        self.assertTrue(snap.can_go_previous)  # restart at 0 s
        self.assertTrue(snap.can_go_next)

    def test_metadata_dict_has_mpris_and_xesam_keys(self):
        snap = mpris.MprisSnapshot(title="Film", track_id="/org/mpris/MediaPlayer2/Track/x",
                                   length_us=120_000_000, artist="")
        data = mpris.metadata_dict(snap)
        self.assertEqual(data["xesam:title"], "Film")
        self.assertEqual(data["mpris:length"], 120_000_000)
        self.assertEqual(data["mpris:trackid"], "/org/mpris/MediaPlayer2/Track/x")
        self.assertEqual(data["xesam:artist"], [])


class ServiceTests(unittest.TestCase):
    def test_publish_emits_every_player_property_once(self):
        bus = _FakeBus()
        service = mpris.MprisService(bus, mpris.WindowAdapter(_Window()))
        service.publish()
        self.assertEqual(bus.published, [service])
        self.assertEqual(len(bus.emitted), 1)
        interface, changed = bus.emitted[0]
        self.assertEqual(interface, mpris.PLAYER_INTERFACE)
        self.assertEqual(changed["PlaybackStatus"], "Playing")
        self.assertIn("Metadata", changed)

    def test_refresh_emits_only_on_change(self):
        bus = _FakeBus()
        window = _Window()
        service = mpris.MprisService(bus, mpris.WindowAdapter(window))
        service.publish()
        bus.emitted.clear()
        service.refresh()  # unchanged
        self.assertEqual(bus.emitted, [])
        window.device_state = "PAUSED"
        service.refresh()
        self.assertEqual(len(bus.emitted), 1)
        self.assertEqual(bus.emitted[0][1]["PlaybackStatus"], "Paused")

    def test_invoke_maps_transport_commands(self):
        window = _Window()
        service = mpris.MprisService(_FakeBus(), mpris.WindowAdapter(window))
        service.invoke(mpris.PLAYER_INTERFACE, "PlayPause", None)
        service.invoke(mpris.PLAYER_INTERFACE, "Next", None)
        service.invoke(mpris.PLAYER_INTERFACE, "Previous", None)
        service.invoke(mpris.PLAYER_INTERFACE, "Stop", None)
        service.invoke(mpris.PLAYER_INTERFACE, "Seek", (-2_000_000,))
        service.invoke(mpris.PLAYER_INTERFACE, "SetPosition",
                       (mpris._track_id("/media/Film.mkv"), 10_000_000))
        self.assertEqual(window.calls, ["toggle_play", "next", "prev", "stop",
                                        ("seek_to", 40.0), ("seek_to", 10.0)])

    def test_play_and_pause_are_conditional_on_status(self):
        playing = _Window()
        mpris.MprisService(_FakeBus(), mpris.WindowAdapter(playing)).invoke(
            mpris.PLAYER_INTERFACE, "Play", None)
        self.assertEqual(playing.calls, [])  # already playing
        mpris.MprisService(_FakeBus(), mpris.WindowAdapter(playing)).invoke(
            mpris.PLAYER_INTERFACE, "Pause", None)
        self.assertEqual(playing.calls, ["toggle_play"])
        paused = _Window(device_state="PAUSED")
        mpris.MprisService(_FakeBus(), mpris.WindowAdapter(paused)).invoke(
            mpris.PLAYER_INTERFACE, "Play", None)
        self.assertEqual(paused.calls, ["toggle_play"])

    def test_external_playback_is_never_controlled(self):
        window = _Window(external=True)
        service = mpris.MprisService(_FakeBus(), mpris.WindowAdapter(window))
        for method in ("PlayPause", "Next", "Previous", "Stop", "Play", "Pause"):
            service.invoke(mpris.PLAYER_INTERFACE, method, None)
        self.assertEqual(window.calls, [])

    def test_set_position_for_other_track_is_ignored(self):
        window = _Window()
        service = mpris.MprisService(_FakeBus(), mpris.WindowAdapter(window))
        service.invoke(mpris.PLAYER_INTERFACE, "SetPosition",
                       (mpris.DEFAULT_TRACK, 10_000_000))
        self.assertEqual(window.calls, [])

    def test_root_commands_raise_and_quit(self):
        window = _Window()
        calls = []
        window.app = types.SimpleNamespace(quit=lambda: calls.append("quit"))
        service = mpris.MprisService(_FakeBus(), mpris.WindowAdapter(window))
        service.invoke(mpris.ROOT_INTERFACE, "Raise", None)
        service.invoke(mpris.ROOT_INTERFACE, "Quit", None)
        self.assertEqual(window.calls, ["present"])
        self.assertEqual(calls, ["quit"])

    def test_property_value_reads_root_and_player(self):
        service = mpris.MprisService(_FakeBus(), mpris.WindowAdapter(_Window()))
        self.assertEqual(service.property_value(mpris.ROOT_INTERFACE, "Identity"), "SmoothCast")
        self.assertEqual(service.property_value(mpris.PLAYER_INTERFACE, "Position"), 42_000_000)
        self.assertIsNone(service.property_value("org.example.Nope", "X"))


_LIVE_SCRIPT = r"""
import os, subprocess, sys, threading, time, types
sys.path.insert(0, SRC)
addr = subprocess.run(["dbus-daemon", "--session", "--print-address=1", "--fork"],
                      capture_output=True, text=True, check=True).stdout.strip()
os.environ["DBUS_SESSION_BUS_ADDRESS"] = addr
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
import mpris

class Tracker:
    duration = 120.0; known = True; playing = True
    def value(self): return 42.0

class Window:
    external = False; now_playing = "/media/Film.mkv"; device_state = "PLAYING"
    tracker = Tracker(); media = types.SimpleNamespace(duration=120.0)
    queue = ["/media/Film.mkv", "/media/Next.mkv"]; busy = False; app = None
    calls = []
    def toggle_play(self): self.calls.append("toggle_play")
    def action_stop(self): self.calls.append("stop")
    def on_next(self): self.calls.append("next")
    def on_prev(self): self.calls.append("prev")
    def seek_to(self, t): self.calls.append(("seek_to", round(t, 3)))
    def present(self): self.calls.append("present")

window = Window()
conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
service = mpris.start(window, connection=conn)
assert service is not None, "service did not start"
loop = GLib.MainLoop()
results = {}

def client():
    time.sleep(0.2)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(interface, method, params=None):
        return bus.call_sync(mpris.BUS_NAME, mpris.OBJECT_PATH, interface, method,
                             params, None, Gio.DBusCallFlags.NONE, -1, None)
    try:
        props = call("org.freedesktop.DBus.Properties", "GetAll",
                     GLib.Variant("(s)", (mpris.PLAYER_INTERFACE,))).unpack()[0]
        results["status"] = props["PlaybackStatus"]
        results["identity"] = call("org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (mpris.ROOT_INTERFACE, "Identity"))).unpack()[0]
        call(mpris.PLAYER_INTERFACE, "PlayPause")
        call(mpris.PLAYER_INTERFACE, "Next")
        call(mpris.PLAYER_INTERFACE, "Seek", GLib.Variant("(x)", (-2_000_000,)))
        results["position"] = call("org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (mpris.PLAYER_INTERFACE, "Position"))).unpack()[0]
        results["calls"] = list(window.calls)
    except Exception as exc:
        results["error"] = repr(exc)
    finally:
        GLib.idle_add(loop.quit)

threading.Thread(target=client, daemon=True).start()
GLib.timeout_add(8000, lambda: (loop.quit(), False)[1])
loop.run()
assert "error" not in results, results.get("error")
assert results["status"] == "Playing", results
assert results["identity"] == "SmoothCast", results
assert results["position"] == 42_000_000, results
assert results["calls"] == ["toggle_play", "next", ("seek_to", 40.0)], results
print("LIVE OK")
"""


def _gi_available() -> bool:
    """PyGObject is present on desktops but absent from the portable CI image."""
    result = subprocess.run([sys.executable, "-I", "-c", "import gi"],
                            capture_output=True, text=True, timeout=60,
                            env={"PATH": os.environ.get("PATH", "")})
    return result.returncode == 0


@unittest.skipUnless(sys.platform.startswith("linux"), "MPRIS2 is Linux-only")
class LiveBusTests(unittest.TestCase):
    def test_real_dbus_round_trip(self):
        if shutil.which("dbus-daemon") is None:
            self.skipTest("dbus-daemon is not installed")
        if not _gi_available():
            self.skipTest("PyGObject (gi) is not installed")
        code = _LIVE_SCRIPT.replace("SRC", repr(str(ROOT / "src")))
        env = {"PATH": os.environ.get("PATH", "")}
        result = subprocess.run([sys.executable, "-I", "-c", code],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LIVE OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
