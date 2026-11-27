"""Pure address and interface policy for receiver-facing URLs (#210). No I/O.

Formats URLs safely for IPv4/IPv6, refuses addresses a receiver cannot use
(link-local with zone ids, loopback, unspecified), ranks candidate source
addresses, and scores interfaces so virtual/VPN adapters lose unless they are
the real route to the receiver.
"""
from __future__ import annotations

import ipaddress
import re

VIRTUAL_PREFIXES = ("docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "lo", "cni", "flannel")
VPN_PREFIXES = ("tun", "tap", "wg", "tailscale", "zt", "utun", "ppp", "nordlynx", "proton")


def parse(host) -> ipaddress._BaseAddress | None:
    """IP address from text, dropping any ``%zone``; None if not an address."""
    text = str(host or "").strip().strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def usable_for_receiver(host) -> bool:
    """False for loopback, unspecified, multicast and IPv6 link-local (zone-bound)."""
    ip = parse(host)
    if ip is None:
        return False
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        return False
    return not (ip.version == 6 and ip.is_link_local)


def host_for_url(host) -> str | None:
    """Host text for a URL: IPv6 bracketed, zone stripped; None if unusable."""
    if not usable_for_receiver(host):
        return None
    ip = parse(host)
    return f"[{ip}]" if ip.version == 6 else str(ip)


def url(scheme: str, host, port: int, path: str = "/") -> str | None:
    h = host_for_url(host)
    if h is None or not isinstance(port, int) or not 0 < port < 65536:
        return None
    return f"{scheme}://{h}:{port}{path if path.startswith('/') else '/' + path}"


def rank_source(addr, prefer_ipv6: bool = False) -> int:
    """Lower is better: private IPv4 / ULA, then global, then others; unusable excluded (99)."""
    ip = parse(addr)
    if ip is None or not usable_for_receiver(addr):
        return 99
    if ip.version == 4:
        base = 0 if ip.is_private else 2
        return base + (1 if prefer_ipv6 else 0)
    base = 0 if ip.is_private else 1  # ULA
    return base + (0 if prefer_ipv6 else 1)


def interface_kind(name: str) -> str:
    n = str(name or "").lower()
    if n.startswith(VPN_PREFIXES):
        return "vpn"
    if n.startswith(VIRTUAL_PREFIXES) or re.match(r"^(veth|docker)", n):
        return "virtual"
    return "physical"


def score_interface(name: str, is_route_to_receiver: bool = False) -> int:
    """Higher is better. The real route always wins; otherwise virtual/VPN lose."""
    if is_route_to_receiver:
        return 100
    return {"physical": 50, "vpn": 5, "virtual": 0}[interface_kind(name)]


def route_warning(name: str) -> str | None:
    """Plain-language caution when the receiver route runs through a tunnel."""
    if interface_kind(name) == "vpn":
        return ("Your connection to the receiver goes through a VPN. Enable local network "
                "(LAN) access or split tunnelling so the TV can reach this computer.")
    return None
