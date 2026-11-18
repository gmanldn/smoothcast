"""Validate user-provided remote media URLs before invoking catt."""
from __future__ import annotations

from urllib.parse import urlsplit


def validate_media_url(value: str) -> str:
    """Return an HTTP(S) URL; reject local paths, control characters and credentials."""
    url = str(value).strip()
    if not url or any(ch.isspace() for ch in url):
        raise ValueError("Enter a valid HTTP or HTTPS media URL")
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only HTTP and HTTPS media URLs are supported")
        if parsed.username or parsed.password:
            raise ValueError("URLs containing usernames or passwords are not supported")
        _ = parsed.port  # Reject malformed port numbers.
    except ValueError as exc:
        raise ValueError(f"Invalid media URL: {exc}") from exc
    return url
