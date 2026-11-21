"""Tests for the locally generated room join image."""
from struct import unpack

import pytest

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


def test_qr_emits_a_square_image_for_the_current_endpoint():
    pytest.importorskip("segno")
    first = qr_png("http://192.168.100.200:65535/")
    second = qr_png("http://192.168.100.201:65534/")
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = unpack(">II", first[16:24])
    assert width == height and 100 <= width <= 180
    assert first != second
