"""Encode a LAN room link locally for phone pairing."""
from io import BytesIO
import re


def qr_png(url: str) -> bytes:
    """Return a high contrast QR image containing only the room address."""
    # Only the numeric endpoint from Portal.url belongs in a join QR.
    if not re.fullmatch(r"http://(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}/", url):
        raise ValueError("Expected a numeric LAN room URL")
    import segno

    image = BytesIO()
    segno.make_qr(url, error="m").save(image, kind="png", scale=4, border=4)
    return image.getvalue()
