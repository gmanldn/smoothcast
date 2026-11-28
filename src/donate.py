"""Optional donation link (Stripe-hosted Payment Link).

The app never handles payment data: it only opens a Stripe-hosted page in the
browser. The link is hidden unless it is a valid https Stripe URL.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

# Set to the Payment Link once created (https://buy.stripe.com/...).
DONATE_URL = ""
ENV_VAR = "SMOOTHCAST_DONATE_URL"
_ALLOWED_HOSTS = {"buy.stripe.com", "donate.stripe.com"}


def donation_url(value: str | None = None) -> str | None:
    """Return the configured donation URL, or None when unset or unsafe."""
    raw = (value if value is not None else os.environ.get(ENV_VAR) or DONATE_URL).strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.hostname not in _ALLOWED_HOSTS
            or parts.username or parts.password or port not in (None, 443)):
        return None
    return raw
