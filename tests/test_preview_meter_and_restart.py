"""Local preview levels and the back-to-start control.

Playing a film in the embedded preview must drive the line meters from that
file, and the transport gains a control that returns to the very beginning of
whatever is playing (cast or local preview).
"""
from __future__ import annotations

from pathlib import Path
import textwrap
import unittest

from gui_source import legacy_self, main_window_methods
import settings
import streamer

ROOT = Path(__file__).resolve().parents[1]
CAST_AV = ROOT / "src" / "cast_av.py"
CAST_UI = ROOT / "src" / "cast_ui.py"
CAST_SESSION = ROOT / "src" / "cast_session.py"


def method_source(source: str, name: str) -> str:
    """Slice one method body out of a module's source text."""
    start = source.index(f"def {name}(")
    rest = source[start:]
    end = rest.find("\n    def ", 1)
    return rest if end < 0 else rest[:end]


def extracted(*names, streamer_module=streamer):
    """Compile real MainWindow methods with only the collaborators they use."""
    code = "class Methods:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(main_window_methods()[name]), "    ")
        for name in names
    )
    namespace = {"streamer": streamer_module, "settings": settings}
    exec(compile(code, "<preview-methods>", "exec"), namespace)  # noqa: S102 - test harness
    return namespace["Methods"]


class LocalPreviewMeterTests(unittest.TestCase):
    def test_meter_follows_the_local_preview_position(self):
        methods = extracted("_meter_position")

        class Stream:
            def __init__(self, playing, timestamp):
                self.playing = playing
                self.timestamp = timestamp

            def get_playing(self):
                return self.playing

            def get_timestamp(self):
                return self.timestamp

        class Window(methods):
            _local_video_path = "/films/a.mkv"

            def __init__(self, stream):
                self.stream = stream
                self.tracker = type("Tracker", (), {"value": lambda _self: 12.5})()

            def _local_stream(self):
                return self.stream

        playing = Window(Stream(True, 42_000_000))
        self.assertEqual(playing._meter_position(), 42.0)
        paused = Window(Stream(False, 42_000_000))
        self.assertIsNone(paused._meter_position())
        casting = Window(None)
        casting._local_video_path = None
        self.assertEqual(casting._meter_position(), 12.5)

    def test_preview_chain_matches_the_configured_audio_profile(self):
        methods = extracted("_preview_monitor_chain")
        window = methods()
        window.cfg = {"audio": "dialogue", "audio_gain": 3.0}
        chain, hint = window._preview_monitor_chain()
        self.assertEqual(chain, streamer.audio_filters("dialogue", 3.0))
        self.assertTrue(chain)
        self.assertIn("Local preview", hint)
        self.assertIn("+3 dB", hint)

    def test_preview_without_gain_keeps_the_plain_hint(self):
        methods = extracted("_preview_monitor_chain")
        window = methods()
        window.cfg = {"audio": "original", "audio_gain": 0}
        chain, hint = window._preview_monitor_chain()
        self.assertEqual(chain, streamer.audio_filters("original", 0.0))
        self.assertIn("Local preview", hint)
        self.assertNotIn("dB", hint)

    def test_preview_playback_starts_and_stops_the_meter(self):
        source = legacy_self(CAST_AV.read_text(encoding="utf-8"))
        toggle = method_source(source, "_toggle_local_preview")
        self.assertIn("self._start_local_meter(", toggle)
        self.assertIn("self._stop_local_meter()", toggle)
        prepared = method_source(source, "_on_local_prepared")
        self.assertIn("self._start_local_meter(start)", prepared)
        unload = method_source(source, "_unload_local_video")
        self.assertIn("self._stop_local_meter()", unload)
        tick = method_source(source, "_meter_tick")
        self.assertIn("self._meter_position()", tick)

    def test_local_meter_never_clears_a_cast_meter(self):
        stop = method_source(legacy_self(CAST_AV.read_text(encoding="utf-8")), "_stop_local_meter")
        self.assertIn("if self._local_video_path is None:", stop)


class BackToStartTests(unittest.TestCase):
    def test_back_to_start_seeks_to_zero(self):
        methods = extracted("_back_to_start")
        window = methods()
        seen = []
        window.seek_to = seen.append
        window._back_to_start()
        self.assertEqual(seen, [0.0])

    def test_transport_exposes_the_control(self):
        source = CAST_UI.read_text(encoding="utf-8")
        self.assertIn('"media-skip-backward-symbolic", "Back to start (Home)"', source)
        controls = source[source.index("self.transport_controls = ("):
                          source.index("for index, widget in enumerate")]
        self.assertIn("self.start_button", controls)
        sensitivity = source[source.index("for button in (self.start_button"):
                             source.index("has_queue = bool(self.queue)")]
        self.assertIn("button.set_sensitive(can_seek)", sensitivity)
        self.assertIn('add("Home", self._back_to_start)', source)

    def test_ui_mixin_owns_the_transport_seek_actions(self):
        source = CAST_UI.read_text(encoding="utf-8")
        self.assertIn("def _back_to_start", source)
        # UI-only shortcut helper, kept out of the session mixin's read budget.
        self.assertIn("def _seek_percent", source)
        self.assertNotIn("def _seek_percent", CAST_SESSION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
