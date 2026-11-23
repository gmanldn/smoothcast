"""Tests for the 1920x1080 join slate used for idle TVs and /join-slate.png."""
from struct import unpack

import pytest

import portal_join
from portal_join import SLATE_SIZE, render_join_slate

pytest.importorskip("segno")
pytest.importorskip("PIL")

URL = "http://192.168.1.20:8080/"


def test_slate_png_is_full_hd():
    png = render_join_slate(URL, "Lounge")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert unpack(">II", png[16:24]) == SLATE_SIZE == (1920, 1080)


def test_slate_contains_the_qr_and_is_not_blank():
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(render_join_slate(URL, "Lounge"))) as image:
        colours = image.convert("RGB").getcolors(maxcolors=1 << 20)
    assert colours is not None and len(colours) > 2
    assert render_join_slate(URL, "Lounge") != render_join_slate(
        "http://192.168.1.21:8080/", "Lounge")


@pytest.mark.parametrize("url", [
    "http://192.168.1.2:8080/?pin=123456",
    "http://user:pw@192.168.1.2:8080/",
    "http://smoothcast.local:8080/",
])
def test_slate_refuses_credentials_and_non_numeric_links(url):
    with pytest.raises(ValueError):
        render_join_slate(url, "Lounge")


@pytest.mark.parametrize("name", ["", "   ", "\x00\n\t", "x" * 5000, "Café 🎬"])
def test_slate_tolerates_hostile_room_names(name):
    assert render_join_slate(URL, name)[:4] == b"\x89PNG"


def test_room_name_is_single_line_bounded_and_defaulted():
    assert portal_join._slate_room_name("a\nb\x00c") == "abc"
    assert len(portal_join._slate_room_name("x" * 500)) == 40
    assert portal_join._slate_room_name("\n") == "SmoothCast"
