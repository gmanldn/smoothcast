"""Validation for guest-supplied direct media URLs (#334). Pure; no fetch at enqueue.

``validate`` is the enqueue check (syntax + literal-address policy).
``revalidate_resolved`` must be called at playback with the addresses the host
actually resolved (and again for each redirect hop), blocking SSRF/DNS rebinding.
``summary`` is the credential-free text safe to show other guests.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

MAX_LEN = 2048
ALLOWED_PORTS = {None, 80, 443, 8000, 8080, 8443}
_BAD_HOSTS = {"localhost", "metadata", "metadata.google.internal"}
_BAD_SUFFIX = (".local", ".localdomain", ".internal", ".lan", ".home", ".corp")
_CTRL = re.compile(r"[\x00-\x20\x7f\\]")


def _addr_ok(ip) -> bool:
    return ip.is_global and not ip.is_multicast


def validate(url: str) -> tuple[str | None, str]:
    """(canonical_url, "") or (None, reason)."""
    if not isinstance(url, str) or not url.strip():
        return None, "Enter a link."
    url = url.strip()
    if len(url) > MAX_LEN:
        return None, "That link is too long."
    if _CTRL.search(url):
        return None, "That link has invalid characters."
    try:
        parts = urlsplit(url)
        port = parts.port
        host = (parts.hostname or "").rstrip(".").lower()
    except ValueError:
        return None, "That link is not valid."
    if parts.scheme not in ("http", "https"):
        return None, "Only http and https links are supported."
    if parts.username or parts.password:
        return None, "Links with a username or password are not accepted."
    if not host or port not in ALLOWED_PORTS:
        return None, "That address or port is not allowed."
    if host in _BAD_HOSTS or host.endswith(_BAD_SUFFIX):
        return None, "Local addresses are not allowed."
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host):      # decimal/octal/hex IPv4 tricks
            return None, "That address is not allowed."
        ip = None
    if ip is not None and not _addr_ok(ip):
        return None, "Private and local addresses are not allowed."
    netloc = host if ":" not in host else f"[{host}]"
    if port:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), ""


def revalidate_resolved(url: str, resolved: list[str]) -> tuple[bool, str]:
    """At playback: the URL must still validate and every resolved address be public."""
    canon, why = validate(url)
    if canon is None:
        return False, why
    if not resolved:
        return False, "The link could not be resolved."
    for text in resolved:
        try:
            if not _addr_ok(ipaddress.ip_address(text)):
                return False, "The link now points to a private address."
        except ValueError:
            return False, "The link resolved to an invalid address."
    return True, ""


def summary(url: str) -> str:
    """Host + shortened path, never query strings, fragments or credentials."""
    try:
        p = urlsplit(url)
        path = p.path if len(p.path) <= 40 else p.path[:37] + "…"
        return f"{p.hostname or ''}{path}"
    except ValueError:
        return "link"
