"""Contract checks for the GTK-free Google Cast backend seam."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, "src")

import castctl
from gui_source import main_window_methods


def test_catt_adapter_satisfies_the_transitional_protocol():
    assert isinstance(castctl.CattBackend(), castctl.CastBackend)


def test_catt_adapter_preserves_scan_and_status_contract():
    scan_payload = (
        '{"Living Room": {"host": "192.168.1.20", "port": 8009, '
        '"model_name": "Chromecast", "uuid": "receiver-1"}}'
    )
    status_payload = '{"player_state": "PLAYING", "current_time": 12.5}'
    with mock.patch.object(
        castctl,
        "_run",
        side_effect=[
            subprocess.CompletedProcess("catt", 0, scan_payload, ""),
            subprocess.CompletedProcess("catt", 0, status_payload, ""),
        ],
    ):
        backend = castctl.CattBackend()
        devices = backend.scan(timeout=1)
        status = backend.info("Living Room", timeout=2)

    assert devices == [
        castctl.Device("Living Room", "192.168.1.20", 8009, "Chromecast", "", "receiver-1")
    ]
    assert status == {"player_state": "PLAYING", "current_time": 12.5}


def test_public_helpers_dispatch_through_the_active_backend():
    fake_backend = mock.Mock(spec=castctl.CastBackend)
    fake_backend.scan.return_value = [castctl.Device("Test TV")]
    fake_backend.info.return_value = {"player_state": "PAUSED"}
    fake_backend.command.return_value = (True, "accepted")

    with mock.patch.object(castctl, "_backend", fake_backend):
        assert castctl.scan(timeout=3) == [castctl.Device("Test TV")]
        assert castctl.info("Test TV", timeout=4) == {"player_state": "PAUSED"}
        assert castctl.command("Test TV", "pause", timeout=5) == (True, "accepted")

    fake_backend.scan.assert_called_once_with(3)
    fake_backend.info.assert_called_once_with("Test TV", 4)
    fake_backend.command.assert_called_once_with("Test TV", "pause", timeout=5)


def test_push_status_capability_and_subscription_dispatch():
    fake_backend = mock.Mock(spec=castctl.CastBackend)
    fake_backend.supports_push_status = True
    unsubscribe = mock.Mock()
    fake_backend.subscribe.return_value = unsubscribe
    listener = mock.Mock()
    with mock.patch.object(castctl, "_backend", fake_backend):
        assert castctl.supports_push_status()
        assert castctl.subscribe("Test TV", listener) is unsubscribe
    fake_backend.subscribe.assert_called_once_with("Test TV", listener)

    assert not castctl.CattBackend().supports_push_status


def test_status_watch_switches_receivers_and_releases_subscriptions():
    owner = SimpleNamespace()
    listeners, stops, dispatched = [], [], []

    def subscribe(device, listener):
        listeners.append((device, listener))
        stop = mock.Mock()
        stops.append(stop)
        return stop

    backend = SimpleNamespace(supports_push_status=True, subscribe=subscribe)
    with mock.patch.object(castctl, "_backend", backend):
        def deliver(callback, status):
            dispatched.append((callback, status))

        receiver_update = mock.Mock()
        assert castctl.watch_status(owner, "A", True, deliver, receiver_update)
        assert castctl.watch_status(owner, "A", True, deliver, receiver_update)
        listeners[0][1]({"player_state": "PLAYING"})
        assert dispatched == [(receiver_update, {"player_state": "PLAYING"})]

        assert castctl.watch_status(owner, "B", True, deliver, receiver_update)
        stops[0].assert_called_once_with()
        assert not castctl.watch_status(owner, "B", False, deliver, receiver_update)
        stops[1].assert_called_once_with()


def test_queue_status_uses_push_events_without_receiver_polling():
    backend = SimpleNamespace(supports_push_status=True)
    backend.subscribe = mock.Mock()
    stopped = mock.Mock()
    listener = {}

    def subscribe(device, callback):
        listener["device"] = device
        listener["callback"] = callback
        return stopped

    backend.subscribe.side_effect = subscribe
    namespace = {
        "castctl": castctl,
        "GLib": SimpleNamespace(idle_add=lambda callback, *args: callback(*args)),
        "Async": SimpleNamespace(run=mock.Mock()),
        "dlna": SimpleNamespace(info=mock.Mock()),
    }
    source = main_window_methods()["_poll_device"]
    exec(compile("class Window:\n" + textwrap.indent(source, "    "),
                 "<queue-status>", "exec"), namespace)
    window = namespace["Window"]()
    window.target = "Receiver A"
    window.poll_busy = False
    window._device = lambda: window.target
    window._dlna_renderer = lambda _device: None
    window._poll_done = mock.Mock()
    window._poll_failed = mock.Mock()

    with mock.patch.object(castctl, "_backend", backend), \
         mock.patch.object(castctl, "info") as info:
        assert window._poll_device()
        assert listener["device"] == "Receiver A"
        listener["callback"]({"player_state": "PLAYING"})
        window._poll_done.assert_called_once_with({"player_state": "PLAYING"})
        namespace["Async"].run.assert_not_called()
        info.assert_not_called()
        window.target = "Receiver B"
        assert window._poll_device()
        stopped.assert_called_once_with()
        assert listener["device"] == "Receiver B"
        window._cast_status_watch.close()
        assert "_cast_status_watch" in main_window_methods()["_on_close"]
