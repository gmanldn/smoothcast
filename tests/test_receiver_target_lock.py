"""P0 #62: receiver ownership does not change via entry, button or dropdown.

Executes real UI handler bodies with GTK-free fakes. Does not scan networks,
create a window, send a Cast command or interact with an active desktop.
"""
from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gui_source import main_window_methods, combined_source
import castctl


def handlers():
    methods = main_window_methods()
    code = "class Handlers:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[name]), "    ")
        for name in ("_add_cast_target", "_on_device_selected")
    )
    changes = []
    namespace = {
        "castctl": castctl,
        "save_config": lambda cfg: changes.append(dict(cfg)),
        "Gtk": SimpleNamespace(INVALID_LIST_POSITION=2 ** 32 - 1),
        "GLib": SimpleNamespace(source_remove=lambda _: None),
    }
    exec(compile(code, "<receiver-handlers>", "exec"), namespace)
    return namespace["Handlers"], changes


class Entry:
    def __init__(self, text=""):
        self.text = text

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text


class Model:
    def __init__(self, values):
        self.values = values

    def get_string(self, index):
        return self.values[index]

    def get_n_items(self):
        return len(self.values)


class Dropdown:
    def __init__(self, values, selected):
        self.model = Model(values)
        self.selected = selected

    def get_selected(self):
        return self.selected

    def get_model(self):
        return self.model

    def set_selected(self, index):
        self.selected = index


def window():
    Handler, saves = handlers()

    class Window(Handler):
        def __init__(self):
            self.cfg = {"device": "192.168.1.10", "cast_targets": []}
            self.cast_ip_entry = Entry("192.168.1.20")
            self.session = None
            self.busy = False
            self._cast_starting = False
            self.external = False
            self._syncing = False
            self._volume_job = None
            self._volume_target = None
            self.devices = []
            self.title_widget = mock.Mock()
            self.messages = []
            self.scans = 0
            self.polls = 0

        def toast(self, text, *, error=False):
            self.messages.append((text, error))

        def _scan_done(self, _devices):
            self.scans += 1

        def _poll_device(self):
            self.polls += 1

        def _set_device_badge(self, _label):
            pass

        def _device(self):
            return self.cfg["device"]

    return Window(), saves


def test_both_input_actions_reject_changes_during_owned_cast():
    for state in ("owned", "preparing", "starting", "external"):
        for signal in ("Return", "Add IP"):
            w, saves = window()
            if state == "owned":
                w.session = mock.Mock()
            if state == "preparing":
                w.busy = True
            if state == "starting":
                w._cast_starting = True
            if state == "external":
                w.external = True
            # Both GUI signals are wired to the same guarded callback.
            assert f'self.cast_ip_entry.connect("activate", lambda _entry: self._add_cast_target())' in combined_source()
            assert f'self.add_ip_button.connect("clicked", lambda _button: self._add_cast_target())' in combined_source()
            w._add_cast_target()
            assert w._device() == "192.168.1.10", (state, signal)
            assert w.cfg["cast_targets"] == [], (state, signal)
            assert not saves and w.polls == 0 and w.scans == 0


def test_idle_manual_entry_validates_saves_and_selects_target():
    w, saves = window()
    w._add_cast_target()
    assert w.cfg["device"] == "192.168.1.20"
    assert w.cfg["cast_targets"] == ["192.168.1.20"]
    assert w.cast_ip_entry.get_text() == ""
    assert len(saves) == 1 and w.polls == 1 and w.scans == 1
    w.cast_ip_entry.set_text("127.0.0.1")
    w._add_cast_target()
    assert len(saves) == 1  # Invalid targets do not save or poll.
    assert w.cfg["device"] == "192.168.1.20"


def test_dropdown_queued_signal_cannot_retarget_owned_or_busy_cast():
    for state in ("owned", "preparing", "starting", "external"):
        w, saves = window()
        setattr(w, {"owned": "session", "preparing": "busy",
                    "starting": "_cast_starting", "external": "external"}[state],
                mock.Mock() if state == "owned" else True)
        dropdown = Dropdown(["192.168.1.10", "192.168.1.20"], selected=1)
        w._on_device_selected(dropdown, None)
        assert w.cfg["device"] == "192.168.1.10"
        assert dropdown.selected == 0
        assert w._syncing is False
        assert not saves and w.polls == 0


def test_idle_dropdown_switches_and_cancels_old_volume_target():
    w, saves = window()
    w._volume_job = 33
    w._volume_target = "192.168.1.10"
    dropdown = Dropdown(["192.168.1.10", "192.168.1.20"], selected=1)
    # Source namespace has inert source_remove; no desktop loop is touched.
    w._on_device_selected(dropdown, None)
    assert w.cfg["device"] == "192.168.1.20"
    assert w._volume_target is None and w._volume_job is None
    assert len(saves) == 1 and w.polls == 1


def test_manual_controls_explicitly_disabled_with_dropdown_during_cast():
    source = main_window_methods()["_refresh_controls"]
    assert "self.cast_ip_entry.set_sensitive(not target_locked)" in source
    assert "self.add_ip_button.set_sensitive(not target_locked)" in source
    assert "self.device_dropdown.set_sensitive(not target_locked)" in source
    assert "self._cast_starting or self.external" in source
