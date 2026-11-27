"""Receiver-facing URLs bracket IPv6 and never publish host-only addresses (#210)."""
import pytest

import network_routes as nr


@pytest.mark.parametrize("host, expected", [
    ("192.168.1.20", "http://192.168.1.20:8767/movie.m3u8"),
    ("fd12:3456::20", "http://[fd12:3456::20]:8767/movie.m3u8"),
    ("[2001:db8::1]", "http://[2001:db8::1]:8767/movie.m3u8"),
    ("2001:0db8:0000::0001", "http://[2001:db8::1]:8767/movie.m3u8"),
])
def test_publishable_hosts(host, expected):
    assert nr.receiver_url(host, 8767, "/movie.m3u8") == expected


@pytest.mark.parametrize("host", [
    "fe80::1", "fe80::1%eth0", "[fe80::1%25wlan0]", "::1", "::", "127.0.0.1",
    "169.254.1.2", "ff02::1", "0.0.0.0", "", "tv.local", "not an ip",
])
def test_host_only_or_invalid_addresses_are_never_published(host):
    assert nr.receiver_url_host(host) is None
    assert nr.receiver_url(host, 8767, "x") is None


def test_rejects_invalid_port():
    assert nr.receiver_url("192.168.1.20", 0) is None
    assert nr.receiver_url("192.168.1.20", 70000) is None
