"""Loopback CASTV2 integration against the real PyChromecast sender."""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pychromecast
import pytest

from fakecast import FakeCastReceiver
from fakecast.receiver import NS_HEARTBEAT, NS_MEDIA, NS_RECEIVER
from pychromecast_backend import PyChromecastBackend


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_receiver_accepts_tls_castv2_and_answers_backend_commands():
    with FakeCastReceiver() as receiver:
        cast = pychromecast.get_chromecast_from_host(
            (
                receiver.host,
                receiver.port,
                uuid.uuid4(),
                "test-model",
                "Loopback Receiver",
            ),
            tries=1,
            retry_wait=0.1,
            timeout=1,
        )
        browser = SimpleNamespace(stop_discovery=lambda: None)

        def discover(*, callback, **_kwargs):
            callback(cast)
            return browser

        backend = PyChromecastBackend(discover=discover)
        updates: list[dict[str, object]] = []
        try:
            devices = backend.scan(timeout=0)
            assert [device.name for device in devices] == ["Loopback Receiver"]
            cast.wait(timeout=2)
            cast.start_app("CC1AD845", timeout=3)
            unsubscribe = backend.subscribe("Loopback Receiver", updates.append)
            assert backend.command(
                "Loopback Receiver", "cast", "http://127.0.0.1/movie.mp4",
            )[0]
            assert wait_for(lambda: any(
                namespace == NS_MEDIA and data.get("type") == "LOAD"
                for namespace, data in receiver.calls
            ))
            assert wait_for(lambda: any(
                status.get("player_state") == "PLAYING" for status in updates
            ))
            assert backend.command("Loopback Receiver", "pause", timeout=3)[0]
            assert wait_for(lambda: any(
                namespace == NS_MEDIA and data.get("type") == "PAUSE"
                for namespace, data in receiver.calls
            ))
            assert any(namespace == NS_HEARTBEAT for namespace, _data in receiver.calls)
            assert any(namespace == NS_RECEIVER for namespace, _data in receiver.calls)
            assert wait_for(lambda: any(
                status.get("player_state") == "PAUSED" for status in updates
            ))
            unsubscribe()
        finally:
            backend.close()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1"])
def test_receiver_refuses_non_loopback_bind(host: str):
    with pytest.raises(ValueError, match="only to loopback"):
        FakeCastReceiver(host=host)


def test_receiver_refuses_unknown_profile():
    with pytest.raises(ValueError, match="generic profile"):
        FakeCastReceiver(profile="chromecast-gen2")
