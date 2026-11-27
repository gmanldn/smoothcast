"""Classify why a receiver is unreachable from the host's network layout (#210).

Pure: takes interface facts and probe outcomes, returns a catalogued error code
(see ``errors.CATALOGUE``) or ``None`` when nothing is wrong. No sockets, no
subprocess; callers gather the facts.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class Iface:
    name: str
    cidr: str                   # e.g. "192.168.1.20/24" or "fd00::2/64"
    vpn: bool = False
    default_route: bool = False


def _network(iface: Iface):
    try:
        return ipaddress.ip_interface(iface.cidr).network
    except ValueError:
        return None


def diagnose(ifaces: list[Iface], receiver_ip: str, *, tcp_ok: bool,
             discovery_ok: bool, peer_arp_seen: bool = True) -> str | None:
    """Most specific catalogue code for the failure, or None if reachable.

    ``tcp_ok``: a TCP connect to the receiver worked. ``discovery_ok``: mDNS/SSDP
    found it. ``peer_arp_seen``: the host could resolve the receiver at layer 2.
    """
    if tcp_ok and discovery_ok:
        return None
    try:
        target = ipaddress.ip_address(receiver_ip)
    except ValueError:
        return "network.subnet_mismatch"
    nets = [(i, _network(i)) for i in ifaces]
    on_link = [i for i, n in nets if n is not None and target.version == n.version and target in n]
    if tcp_ok:                                    # reachable but not discoverable
        return "network.discovery_blocked"
    if not on_link:
        vpn_default = any(i.vpn and i.default_route for i in ifaces)
        return "network.vpn_default_route" if vpn_default else "network.subnet_mismatch"
    real = [i for i in on_link if not i.vpn]
    if len(real) > 1 and any(i.default_route for i in ifaces if i not in real):
        return "network.interface_ambiguous"
    if not peer_arp_seen:
        return "network.client_isolation"
    return "network.vpn_default_route" if any(i.vpn and i.default_route for i in ifaces) else "network.discovery_blocked"
