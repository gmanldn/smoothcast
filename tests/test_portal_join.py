"""Tests for the locally generated room join image."""
from struct import unpack
from types import SimpleNamespace

import pytest

import portal
import portal_join
from portal_join import qr_png


@pytest.mark.parametrize("url", [
    "http://192.168.1.2:8080/?pin=123456",
    "http://192.168.1.2:8080/#secret",
    "http://smoothcast-room.local:8080/",
    "http://user:password@192.168.1.2:8080/",
])
def test_qr_refuses_credentials_and_non_numeric_links(url):
    with pytest.raises(ValueError):
        qr_png(url)


@pytest.mark.parametrize("url", [
    "http://smoothcast.local:8080/",
    "http://SmoothCast.LOCAL:8080/",
    "http://smoothcast-2.local:8080/",
    "http://smoothcast-9.local:65535/",
])
def test_qr_accepts_the_stable_entry_names(url):
    """The printable QR must survive a DHCP change via the stable mDNS name."""
    pytest.importorskip("segno")
    assert qr_png(url).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("url", [
    "http://smoothcast.local/",              # a port is required for the room URL
    "http://smoothcast-1.local:8080/",       # only the -2..-9 fallbacks exist
    "http://smoothcast-10.local:8080/",
    "http://smoothcast.local:8080/?pin=123456",
    "http://smoothcast.local:8080/#x",
    "http://user@SmoothCast.LOCAL:8080/",
    "http://smoothcast.local.evil:8080/",
    "http://evil.example:8080/",
    "https://smoothcast.local:8080/",
])
def test_qr_still_refuses_non_entry_or_secret_links(url):
    with pytest.raises(ValueError):
        qr_png(url)


def test_is_join_url_matches_the_accepted_forms_only():
    for url in ("http://192.168.1.2:8080/", "http://smoothcast.local:8080/",
                "http://smoothcast-2.local:8080/"):
        assert portal_join.is_join_url(url)
    for url in (None, 1, "http://smoothcast.local:8080",
                "http://smoothcast-10.local:8080/", "http://smoothcast.local:8080/x"):
        assert not portal_join.is_join_url(url)


def test_portal_join_url_prefers_an_attached_entry_name():
    instance = portal.Portal.__new__(portal.Portal)
    instance.url = "http://192.168.1.5:8080/"
    instance._entry = None
    assert instance.join_url() == instance.url
    instance.attach_entry(SimpleNamespace(url="http://smoothcast.local:8080/"))
    assert instance.join_url() == "http://smoothcast.local:8080/"
    instance.attach_entry(SimpleNamespace(url=None))       # released name: fall back
    assert instance.join_url() == instance.url
    instance.attach_entry(None)
    assert instance.join_url() == instance.url


def test_qr_emits_a_square_image_for_the_current_endpoint():
    pytest.importorskip("segno")
    first = qr_png("http://192.168.100.200:65535/")
    second = qr_png("http://192.168.100.201:65534/")
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = unpack(">II", first[16:24])
    assert width == height and 100 <= width <= 180
    assert first != second
