"""#244: route-free Linux, macOS and Windows LAN source discovery regressions.

All socket activity, interface lookup, process spawning and DNS are injected
or mocked. No GTK window or receiver is launched by these tests.
"""
from __future__ import annotations

import socket
from types import SimpleNamespace as NS
from unittest import mock

import pytest

import lan_interfaces
import streamer


def rec(address, mask="255.255.255.0", family=socket.AF_INET):
    return NS(family=family, address=address, netmask=mask)


def interfaces(**items):
    return lambda: items


def no_dns(*_args, **_kwargs):
    return []


def choose(records, receiver=None, states=None):
    return lan_interfaces.select_private_lan_ip(
        receiver, interface_addrs=interfaces(**records),
        interface_stats=lambda: states or {},
        hostname_lookup=no_dns,
    )


def test_mac_and_windows_names_select_matching_receiver_subnet_without_default_route():
    # A VPN with a broader mask must not override a matching physical network.
    records = {
        "utun4": [rec("10.0.5.4", "255.0.0.0")],
        "en0": [rec("10.0.5.101", "255.255.255.0")],
        "Ethernet": [rec("192.168.20.11", "255.255.255.0")],
    }
    assert choose(records, "10.0.5.99") == "10.0.5.101"
    assert choose(records, "192.168.20.28") == "192.168.20.11"


def test_up_physical_wins_over_virtual_or_down_interface():
    records = {
        "Docker0": [rec("172.17.0.1", "255.255.0.0")],
        "wg0": [rec("10.6.0.10")],
        "Wi-Fi": [rec("192.168.5.26")],
        "Ethernet": [rec("192.168.5.50")],
    }
    states = {
        "Wi-Fi": NS(isup=True),
        "Ethernet": NS(isup=False),
    }
    assert choose(records, states=states) == "192.168.5.26"


def test_rejects_loopback_link_local_public_reserved_and_ipv6():
    records = {
        "Loopback": [rec("127.0.0.1"), rec("169.254.12.6"),
                     rec("0.0.0.0"), rec("224.0.0.1")],
        "Public": [rec("8.8.8.8"), rec("255.255.255.255")],
        "IPv6": [rec("fd12::2", family=socket.AF_INET6)],
        "Ethernet": [rec("172.23.4.12")],
    }
    assert choose(records, "172.23.4.78") == "172.23.4.12"


def test_absent_netmask_can_fallback_but_prefers_real_matching_network():
    records = {
        "en0": [rec("192.168.4.77", mask=None)],
        "en1": [rec("192.168.4.10", mask="255.255.255.0")],
    }
    assert choose(records, "192.168.4.12") == "192.168.4.10"


def test_malformed_interface_info_never_crashes_or_invents_route():
    records = {
        "odd": [rec("invalid"), rec("10.0.0.2", "this-is-not-a-mask")],
        "down": [rec("192.168.50.5")],
    }
    assert choose(records, "10.0.0.99", states={"down": NS(isup=False)}) == "10.0.0.2"
    assert choose({"odd": [rec("not-an-ip")]}) is None


def test_no_psutil_falls_back_to_private_hostname_addresses_not_external_dns():
    results = [
        (socket.AF_INET, 0, 0, "", ("8.8.8.8", 0)),
        (socket.AF_INET, 0, 0, "", ("127.0.0.1", 0)),
        (socket.AF_INET, 0, 0, "", ("192.168.1.77", 0)),
    ]
    address = lan_interfaces.select_private_lan_ip(
        "192.168.1.20", interface_addrs=lambda: {},
        interface_stats=lambda: {},
        hostname_lookup=lambda *args, **kwargs: results,
    )
    assert address == "192.168.1.77"


def test_interface_permission_error_and_unavailable_dns_returns_none():
    assert lan_interfaces.select_private_lan_ip(
        "192.168.1.20",
        interface_addrs=mock.Mock(side_effect=PermissionError("denied")),
        interface_stats=lambda: {},
        hostname_lookup=mock.Mock(side_effect=OSError("unknown hostname")),
    ) is None


def test_real_route_to_receiver_wins_even_when_interface_enumerator_disagrees():
    fake = mock.MagicMock()
    fake.__enter__.return_value = fake
    fake.getsockname.return_value = ("192.168.44.21", 55010)
    with mock.patch.object(streamer.socket, "socket", return_value=fake), \
         mock.patch.object(streamer.lan_interfaces, "select_private_lan_ip",
                           side_effect=AssertionError("route is authoritative")):
        assert streamer.host_ip("192.168.44.30") == "192.168.44.21"
    fake.connect.assert_called_once_with(("192.168.44.30", 8009))


def test_no_receiver_route_uses_matching_interface_not_public_route():
    with mock.patch.object(streamer.socket, "socket", side_effect=OSError("no route")), \
         mock.patch.object(streamer.lan_interfaces, "select_private_lan_ip",
                           return_value="192.168.50.21") as enumerate_ip, \
         mock.patch.object(streamer.subprocess, "check_output",
                           side_effect=AssertionError("must not call hostname -I")):
        assert streamer.host_ip("192.168.50.45") == "192.168.50.21"
    enumerate_ip.assert_called_once_with("192.168.50.45")


def test_no_receiver_route_or_interface_gives_actionable_error():
    with mock.patch.object(streamer.socket, "socket", side_effect=OSError("no route")), \
         mock.patch.object(streamer.lan_interfaces, "select_private_lan_ip",
                           return_value=None):
        with pytest.raises(streamer.StreamError, match=r"LAN IPv4.*Wi-Fi/Ethernet"):
            streamer.host_ip("192.168.99.22")


def test_no_shell_command_and_portable_enumerator_is_packaged():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/streamer.py").read_text("utf-8")
    manifest = (root / "pyproject.toml").read_text("utf-8")
    assert '["hostname", "-I"]' not in source
    assert '"lan_interfaces"' in manifest
    assert '"psutil>=' in manifest
