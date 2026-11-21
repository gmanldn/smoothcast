"""Loopback-only mDNS discovery for the Cast protocol fake."""
from __future__ import annotations

import pytest
from zeroconf import Zeroconf

from fakecast import FakeCastReceiver
from fakecast.discovery import SERVICE_TYPE
from pychromecast_backend import PyChromecastBackend


def test_in_process_receiver_keeps_advertising_opt_in():
    with FakeCastReceiver() as receiver:
        assert not receiver.advertisement_active
        assert receiver.advertising_error is None


@pytest.mark.multicast
def test_advertisement_has_cast_txt_and_pychromecast_discovers_loopback_receiver():
    backend = PyChromecastBackend()
    with FakeCastReceiver(profile="chromecast-gen2", advertise=True) as receiver:
        if not receiver.advertisement_active:
            pytest.skip(f"loopback mDNS unavailable: {receiver.advertising_error}")
        observer = Zeroconf(interfaces=["127.0.0.1"])
        try:
            service_name = receiver.service_name
            assert service_name is not None
            service = observer.get_service_info(SERVICE_TYPE, service_name, timeout=3000)
            if service is None:
                pytest.skip("loopback multicast discovery is unavailable in this environment")
            properties = service.properties
            assert properties[b"id"]
            assert properties[b"fn"] == b"SmoothCast Test (chromecast-gen2)"
            assert properties[b"md"] == b"chromecast-gen2"
            assert properties[b"ve"]
            assert properties[b"ca"]
            assert properties[b"st"]
            assert service.port == receiver.port
            assert service.parsed_addresses() == ["127.0.0.1"]

            devices = backend.scan(timeout=5)
            fake = [
                device for device in devices
                if device.host == "127.0.0.1" and device.port == receiver.port
            ]
            if not fake:
                pytest.skip("Cast mDNS browser cannot receive loopback multicast here")
            assert len(fake) == 1
            assert fake[0].host == "127.0.0.1"
            assert fake[0].port == receiver.port
            assert fake[0].model == "chromecast-gen2"
            receiver.reboot(delay=0.01)
            assert receiver.advertisement_active
            assert receiver.service_name == service_name
        finally:
            observer.close()
            backend.close()
