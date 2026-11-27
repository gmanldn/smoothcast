"""Encode a LAN room link locally for phone pairing."""
from io import BytesIO
from ipaddress import IPv4Address
import re

import lan_guard


_ROOM_URL = re.compile(r"http://(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}/")
# The stable mDNS entry address (``smoothcast.local`` and numbered fallbacks) with
# a required port; validated by ``lan_guard.is_entry_host`` so both lists agree.
_ENTRY_URL = re.compile(r"http://([a-z0-9][a-z0-9.-]*:[0-9]{1,5})/", re.IGNORECASE)


def is_room_url(url: object) -> bool:
    """True for the plain numeric LAN room URL that may appear in a join QR."""
    if not isinstance(url, str) or not _ROOM_URL.fullmatch(url):
        return False
    host, port = url[len("http://"):-1].rsplit(":", 1)
    try:
        IPv4Address(host)
    except ValueError:
        return False
    return 1 <= int(port) <= 65535


def is_join_url(url: object) -> bool:
    """True for a scannable room link: the numeric endpoint or the stable entry name."""
    if is_room_url(url):
        return True
    match = _ENTRY_URL.fullmatch(url) if isinstance(url, str) else None
    return bool(match and lan_guard.is_entry_host(match.group(1))
                and 1 <= int(match.group(1).rsplit(":", 1)[1]) <= 65535)


def qr_png(url: str) -> bytes:
    """Return a high contrast QR image containing only the room address.

    Accepts the numeric LAN endpoint or the stable ``smoothcast.local`` entry
    name, so a printed code keeps working across DHCP changes. The QR never
    carries a PIN or other secret.
    """
    if not is_join_url(url):
        raise ValueError("Expected a numeric LAN room URL or a smoothcast.local entry URL")
    import segno

    image = BytesIO()
    segno.make_qr(url, error="m").save(image, kind="png", scale=4, border=4)
    return image.getvalue()


SLATE_SIZE = (1920, 1080)
_SLATE_BACKGROUND = (16, 23, 34)
_SLATE_TEXT = (244, 247, 251)
_SLATE_MUTED = (160, 174, 192)
_MAX_ROOM_NAME = 40


def _slate_room_name(room_name: str) -> str:
    """Printable, single-line, length-bounded room name for the slate."""
    cleaned = "".join(ch for ch in str(room_name) if ch.isprintable()).strip()
    return cleaned[:_MAX_ROOM_NAME] or "SmoothCast"


def render_join_slate(url: str, room_name: str) -> bytes:
    """Return a 1920x1080 PNG with the join QR, short address and room name.

    The slate is cast to a TV and scanned from the TV screen, so it accepts only
    the numeric endpoint (the address the TV itself reached) and never a PIN or
    credential. Raises ``ValueError`` for any other URL and ``ImportError`` when
    segno or Pillow is unavailable.
    """
    if not is_room_url(url):
        raise ValueError("Expected a numeric LAN room URL")
    qr_bytes = qr_png(url)
    from PIL import Image, ImageDraw, ImageFont

    width, height = SLATE_SIZE
    canvas = Image.new("RGB", SLATE_SIZE, _SLATE_BACKGROUND)
    with Image.open(BytesIO(qr_bytes)) as qr:
        side = 640
        code = qr.convert("RGB").resize((side, side), Image.Resampling.NEAREST)
    canvas.paste(code, ((width - side) // 2, 200))
    draw = ImageDraw.Draw(canvas)

    def centred(text: str, y: int, size: int, colour: tuple[int, int, int]) -> None:
        font = ImageFont.load_default(size=size)
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (right - left)) // 2 - left, y), text, font=font, fill=colour)

    centred(_slate_room_name(room_name), 60, 88, _SLATE_TEXT)
    centred("Scan to join on your phone", 880, 48, _SLATE_MUTED)
    centred(url[len("http://"):-1], 950, 72, _SLATE_TEXT)
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
