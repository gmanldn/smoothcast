"""``doctor`` check: does the route to the receiver run through a VPN? (#211, #210)"""
from __future__ import annotations

import platform

import address_policy
from doctor import FAIL, PASS, WARN, Result, receiver  # noqa: F401 - FAIL re-exported for callers


def vpn_route(interface: str | None) -> Result:
    """Warn when the route to the receiver runs through a VPN or tunnel interface."""
    warning = address_policy.route_warning(interface or "")
    if warning:
        return Result("vpn", WARN, f"Receiver route uses tunnel interface {interface}", warning)
    return Result("vpn", PASS, "Receiver route is not through a VPN")


def receiver_interface(host: str) -> str | None:
    import network_routes

    source, _error = network_routes.route_source(host)
    return network_routes.interface_name(host, source, os_name=platform.system())


def receiver_checks(host: str) -> list:
    return [lambda: receiver(host), lambda: vpn_route(receiver_interface(host))]
