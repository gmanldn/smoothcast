"""Portable, receiver-aware LAN address selection without invoking OS shells.

Installed SmoothCast uses psutil to enumerate IPv4 interfaces on Linux, macOS
and Windows. Source-only CI may not install app dependencies; in that case
getaddrinfo provides a safe, albeit less complete, fallback.
"""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping

psutil = _UNSET = object()   # imported on first use: ~25 ms we keep off the startup path (#463)


def _load_psutil():
    global psutil
    if psutil is _UNSET:
        try:
            import psutil as module
        except ImportError:  # CI source tests can run without installed runtime deps.
            module = None
        psutil = module
    return psutil


_VIRTUAL_PREFIXES = (
    "docker", "veth", "br-", "virbr", "vmnet", "vbox", "tailscale",
    "tun", "tap", "utun", "wg", "zt", "lo",
)


def _private_address(text: object) -> ipaddress.IPv4Address | None:
    try:
        ip = ipaddress.IPv4Address(str(text))
    except ipaddress.AddressValueError:
        return None
    if not ip.is_private or ip.is_loopback or ip.is_link_local or (
        ip.is_unspecified or ip.is_multicast or ip.is_reserved
    ):
        return None
    return ip


def _netmask_match(
    source: ipaddress.IPv4Address, mask: object, receiver: ipaddress.IPv4Address | None,
) -> int:
    """Return matching prefix length; minus one if unknown or not in subnet."""
    if receiver is None or not mask:
        return -1
    try:
        network = ipaddress.IPv4Network(f"{source}/{mask}", strict=False)
        return network.prefixlen if receiver in network else -1
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        return -1


def select_private_lan_ip(
    receiver: str | None = None, *, interface_addrs=None,
    interface_stats=None, hostname_lookup=None,
) -> str | None:
    """Prefer a live receiver-subnet interface, then a non-virtual private IP.

    No packets are transmitted, and no executable is launched. Injected
    interface functions support deterministic tests; errors fail closed.
    """
    try:
        target = ipaddress.IPv4Address(receiver) if receiver else None
    except ipaddress.AddressValueError:
        target = None
    if interface_addrs is None or interface_stats is None:
        ps = _load_psutil()
        if interface_addrs is None:
            interface_addrs = ps.net_if_addrs if ps else lambda: {}
        if interface_stats is None:
            interface_stats = ps.net_if_stats if ps else lambda: {}
    if hostname_lookup is None:
        hostname_lookup = socket.getaddrinfo

    try:
        interfaces = interface_addrs()
        states = interface_stats()
    except (OSError, RuntimeError, ValueError):
        interfaces, states = {}, {}
    if not isinstance(interfaces, Mapping):
        interfaces = {}
    if not isinstance(states, Mapping):
        states = {}

    candidates: list[tuple[tuple[int, int, int, int], str]] = []
    for name, addresses in interfaces.items():
        state = states.get(name)
        if state is not None and not getattr(state, "isup", False):
            continue
        physical = not str(name).lower().startswith(_VIRTUAL_PREFIXES)
        for record in addresses:
            if getattr(record, "family", None) != socket.AF_INET:
                continue
            ip = _private_address(getattr(record, "address", ""))
            if ip is None:
                continue
            prefix = _netmask_match(ip, getattr(record, "netmask", None), target)
            # A matching receiver network always wins over the default route,
            # then prefer real interfaces over VPN/virtual adapters.
            score = (int(prefix >= 0), prefix, int(physical), -int(ip))
            candidates.append((score, str(ip)))
    if candidates:
        return max(candidates, key=lambda entry: entry[0])[1]

    # Last resort if psutil is unavailable or the OS interface call failed:
    # host DNS can expose multiple addresses but cannot prove subnet masks.
    try:
        results = hostname_lookup(socket.gethostname(), None, family=socket.AF_INET)
    except (OSError, ValueError):
        return None
    resolved = sorted({
        str(ip) for item in results
        if len(item) >= 5 and (ip := _private_address(item[4][0])) is not None
    })
    return resolved[0] if resolved else None
