"""Receiver UUID/name reconciliation contracts (P0 SC-008).

Runs real scan/selection handlers through GTK-free fakes. No mDNS traffic,
Chromecast commands or desktop windows.
"""
from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gui_source import main_window_methods
import castctl
import cast_targets


def device(name, uuid, host="192.168.1.40"):
    return castctl.Device(name=name, host=host, uuid=uuid)


class Model:
    def __init__(self, names):
        self.names = names

    def get_string(self, index):
        return self.names[index]

    def get_n_items(self):
        return len(self.names)


class Dropdown:
    def __init__(self):
        self.model = Model([])
        self.selected = 0

    def set_model(self, model):
        self.model = model

    def get_model(self):
        return self.model

    def set_selected(self, selected):
        self.selected = selected

    def get_selected(self):
        return self.selected


class Entry:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = value


def window(name="Old TV", uuid="uuid-a"):
    methods = main_window_methods()
    source = "class Discovery:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[method]), "    ")
        for method in ("_scan_done", "_scan_failed", "_on_device_selected",
                       "_add_cast_target", "_device_host")
    )
    saved = []
    namespace = {
        "Gtk": SimpleNamespace(
            StringList=SimpleNamespace(new=lambda names: Model(list(names))),
            INVALID_LIST_POSITION=2 ** 32 - 1,
        ),
        "GLib": SimpleNamespace(source_remove=lambda _: None),
        "castctl": castctl,
        "cast_targets": cast_targets,
        "save_config": lambda cfg: saved.append(dict(cfg)),
    }
    exec(compile(source, "<discovery>", "exec"), namespace)

    class FakeWindow(namespace["Discovery"]):
        def __init__(self):
            self.cfg = {"device": name, "device_uuid": uuid, "cast_targets": []}
            self.devices = []
            self.dlna_devices = []
            self._dlna_by_key = {}
            self.device_dropdown = Dropdown()
            self.device_detail = mock.Mock()
            self.title_widget = mock.Mock()
            self.cast_ip_entry = Entry("192.168.1.100")
            self._volume_job = None
            self._volume_target = None
            self._syncing = False
            self.session = None
            self.busy = False
            self._cast_starting = False
            self.external = False
            self.toasts = []
            self.polls = 0
            self.badges = []

        def toast(self, message, *, error=False):
            self.toasts.append(message)

        def _poll_device(self):
            self.polls += 1

        def _dlna_renderer(self, device=None):
            return None

        def _set_device_badge(self, name, kind=None):
            self.badges.append(name)

    return FakeWindow(), saved


def test_unique_uuid_resolves_only_one_physical_receiver():
    one = device("Living Room", "id-a")
    assert castctl.uniquely_named_device("id-a", [one]) is one
    assert castctl.uniquely_named_device("", [one]) is None
    assert castctl.uniquely_named_device("id-missing", [one]) is None
    assert castctl.uniquely_named_device("id-a", [one, device("Bedroom", "id-a")]) is None
    assert castctl.uniquely_named_device("id-a", [one, device("Living Room", "id-b")]) is None


def test_idle_scan_recovers_renamed_device_and_persists_user_selection():
    w, saves = window()
    w._volume_job = 41  # pending write for previous receiver
    w._volume_target = "Old TV"
    w._scan_done([device("New TV", "uuid-a")])
    assert w.cfg["device"] == "New TV"
    assert w.cfg["device_uuid"] == "uuid-a"
    assert w.device_dropdown.get_model().names == ["New TV"]
    assert w.device_dropdown.get_selected() == 0
    assert len(saves) == 1
    assert w._volume_job is None and w._volume_target is None
    assert w.polls == 1  # status is queried on the new target
    assert "Reconnected renamed Cast receiver" in w.toasts[0]


def test_reused_name_migrates_only_to_saved_uuid_not_the_impostor():
    w, saves = window(name="Living Room", uuid="uuid-a")
    w._scan_done([
        device("Living Room", "uuid-b", "192.168.1.41"),
        device("Kitchen", "uuid-a", "192.168.1.42"),
    ])
    assert w.cfg["device"] == "Kitchen"
    assert len(saves) == 1


def test_ambiguous_or_missing_uuid_never_silently_retargets():
    """INV-001: Ambiguous or missing UUID never retargets a selected receiver."""
    for found in (
        [],
        [device("New TV", "")],
        [device("New TV", "uuid-a"), device("New TV", "uuid-b")],
        [device("New TV", "uuid-a"), device("Other TV", "uuid-a")],
    ):
        w, saves = window()
        w._scan_done(found)
        assert w.cfg["device"] == "Old TV"
        assert saves == []


def test_busy_or_owned_receiver_never_retargets_from_late_scan():
    for field in ("session", "busy", "_cast_starting", "external"):
        w, saves = window()
        setattr(w, field, object() if field == "session" else True)
        w._scan_done([device("Renamed TV", "uuid-a")])
        assert w.cfg["device"] == "Old TV"
        assert saves == []


def test_old_config_learns_uuid_only_from_unique_current_name():
    w, saves = window(name="Living Room", uuid="")
    w._scan_done([device("Living Room", "uuid-a")])
    assert w.cfg["device_uuid"] == "uuid-a"
    assert len(saves) == 1
    ambiguous, changes = window(name="Living Room", uuid="")
    ambiguous._scan_done([device("Living Room", "uuid-a"),
                          device("Living Room", "uuid-b")])
    assert ambiguous.cfg["device_uuid"] == ""
    assert not changes


def test_explicit_selection_updates_uuid_and_manual_target_clears_it():
    w, saves = window(name="Old TV", uuid="uuid-a")
    w._scan_done([device("Old TV", "uuid-a"), device("Bedroom", "uuid-b")])
    w.device_dropdown.set_selected(1)
    w._on_device_selected(w.device_dropdown, None)
    assert w.cfg["device"] == "Bedroom"
    assert w.cfg["device_uuid"] == "uuid-b"
    assert saves[-1]["device_uuid"] == "uuid-b"
    w._add_cast_target()
    assert w.cfg["device"] == "192.168.1.100"
    assert w.cfg["device_uuid"] == ""
    assert saves[-1]["device_uuid"] == ""


def test_discovered_host_requires_one_current_name_match():
    w, _ = window(name="Living Room", uuid="")
    w.devices = [device("Living Room", "uuid-a", "192.168.1.41")]
    assert w._device_host("Living Room") == "192.168.1.41"

    # An incomplete mDNS refresh must not fall back to a cached address.
    w.devices = [device("Living Room", "uuid-a", "")]
    assert w._device_host("Living Room") is None

    # Duplicate friendly names are indistinguishable in the name-based UI.
    w.devices = [
        device("Living Room", "uuid-a", "192.168.1.41"),
        device("Living Room", "uuid-b", "192.168.1.42"),
    ]
    assert w._device_host("Living Room") is None

    # A failed refresh invalidates the old address while preserving selection.
    w.devices = [device("Living Room", "uuid-a", "192.168.1.41")]
    w._scan_failed("network unavailable")
    assert w.cfg["device"] == "Living Room"
    assert w._device_host("Living Room") is None
