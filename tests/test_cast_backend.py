"""Contract checks for the GTK-free Google Cast backend seam."""

from __future__ import annotations

import subprocess
import sys
from unittest import mock

sys.path.insert(0, "src")

import castctl


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
