"""Home-LAN boundary helpers (docs/VISION.md trust model; issue #417).

SmoothCast trusts everyone on the home LAN and nobody else. These pure helpers
decide whether a client address is part of the LAN and which ``Host`` names a
listener answers to, so every HTTP listener can refuse the rest of the world.
"""
from __future__ import annotations

import ipaddress

ENTRY_NAME = "smoothcast.local"


def is_lan_address(value: object) -> bool:
    """True for loopback, link-local and private (RFC 1918 / ULA) addresses."""
    if not isinstance(value, str):
        return False
    text = value.split("%", 1)[0]  # drop an IPv6 zone id
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return bool(address.is_loopback or address.is_link_local or address.is_private)


def allowed_hosts(bind_ips: list[str], port: int, names: list[str] | tuple[str, ...] = ()) -> set[str]:
    """``Host`` header values a listener accepts (lowercase, with and without port)."""
    hosts: set[str] = set()
    labels = ["localhost", "127.0.0.1", ENTRY_NAME, *bind_ips, *names]
    for label in labels:
        label = str(label).lower().rstrip(".")
        if label:
            hosts.add(f"{label}:{port}")
            hosts.add(label)
    return hosts


def is_entry_host(host: str) -> bool:
    """``smoothcast.local`` and its numbered fallbacks (``smoothcast-2.local``), with optional port."""
    import re
    return re.fullmatch(r"smoothcast(?:-[2-9])?\.local(?::\d{1,5})?", str(host).lower().rstrip(".")) is not None
