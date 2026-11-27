"""Opt-in route/HLS diagnostics for a named private-LAN Chromecast target.

All active probes are only invoked by `smoothcast --network-check`. A local
socket route or loopback test cannot certify that another device reaches
the media port; print an exact second-host check instead. GTK-free.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import platform
import re
import socket
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

import address_policy
import castctl
from server import HEALTH_BODY, HEALTH_PATH, PORT


CAST_PORT = 8009
_PRIVATE_LAN = tuple(ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def _lan_source(value: str) -> bool:
    """Require actual RFC1918 ranges, not Python's broader is_private."""
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return any(address in network for network in _PRIVATE_LAN)


_VPN_INTERFACE = re.compile(
    r"^(?:tun|tap|utun|wg|tailscale|ppp|zt|vpn|nordlynx)", re.I
)


def _valid_source(value: str) -> str | None:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return None
    if (address.is_unspecified or address.is_loopback
            or address.is_link_local or address.is_multicast):
        return None
    return str(address)


def receiver_url_host(value: str) -> str | None:
    """Host part of a URL a receiver must fetch, or None if unsafe to publish.

    IPv4 stays bare and IPv6 is bracketed. Link-local, zone-scoped (``%eth0``),
    loopback, multicast and unspecified addresses only mean something on this
    host, so they are never handed to a TV; prefer global/ULA IPv6 or IPv4.
    """
    text = str(value or "").strip().strip("[]")
    if not text or "%" in text:
        return None
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if (address.is_unspecified or address.is_loopback
            or address.is_link_local or address.is_multicast):
        return None
    return f"[{address.compressed}]" if address.version == 6 else str(address)


def receiver_url(host: str, port: int, path: str = "") -> str | None:
    """``http://host:port/path`` for a receiver, IPv6-safe; None if unpublishable."""
    url_host = receiver_url_host(host)
    if url_host is None or not 0 < int(port) < 65536:
        return None
    return f"http://{url_host}:{int(port)}/{path.lstrip('/')}"


def route_source(
    receiver: str, *, socket_factory=socket.socket,
) -> tuple[str | None, str | None]:
    """Determine local source IPv4 without sending any UDP packets."""
    try:
        with socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((receiver, CAST_PORT))
            address = probe.getsockname()[0]
        source = _valid_source(str(address))
        return source, None if source else "No usable local IPv4 for the receiver route"
    except (OSError, ValueError, TypeError) as exc:
        return None, f"Receiver route lookup failed: {type(exc).__name__}"


def interface_name(
    receiver: str, source: str | None, *,
    os_name: str, run=subprocess.run,
) -> str | None:
    """Best-effort OS route metadata, never a proof of receiver reachability."""
    if source is None:
        return None
    if os_name == "Linux":
        command = ["ip", "-j", "route", "get", receiver]
    elif os_name == "Darwin":
        command = ["route", "-n", "get", receiver]
    else:
        return None
    try:
        result = run(
            command, capture_output=True, text=True, timeout=2, check=False,
        )
        if result.returncode != 0:
            return None
        if os_name == "Linux":
            routes = json.loads(result.stdout)
            if not isinstance(routes, list) or not routes:
                return None
            route = routes[0]
            if not isinstance(route, dict) or route.get("prefsrc", route.get("src")) != source:
                return None
            name = str(route.get("dev") or "")
        else:
            match = re.search(r"^\s*interface:\s*([\w.-]+)\s*$", result.stdout, re.M)
            name = match.group(1) if match else ""
        return name if re.fullmatch(r"[\w.-]{1,64}", name) else None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def check_receiver_port(
    receiver: str, *, connect=socket.create_connection,
) -> str:
    """Probe the Cast control port without sending an application command."""
    try:
        with connect((receiver, CAST_PORT), timeout=2):
            return "reachable"
    except (OSError, TimeoutError):
        return "unreachable_or_filtered"


def active_port() -> int:
    """Port of the running HLS stream (it may be a fallback), else the default."""
    try:
        import streamer
        state = streamer.load_session()
        port = urlsplit(state.stream_url).port if state and state.stream_url else None
    except Exception:
        return PORT
    return port if port and 1024 <= port <= 65535 else PORT


def check_local_hls(*, open_url=urlopen, port: int | None = None) -> str:
    """Verify the local HLS HTTP server's exact health response, not LAN reach."""
    port = PORT if port is None else port
    try:
        with open_url(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=2) as response:
            body = response.read(len(HEALTH_BODY) + 1)
            return "healthy" if body == HEALTH_BODY else "unexpected_response"
    except (OSError, ValueError, TimeoutError):
        return "not_responding"


def report(
    receiver: str, *, socket_factory=socket.socket,
    connect=socket.create_connection, open_url=urlopen,
    run=subprocess.run, os_name: str | None = None,
) -> dict:
    """Produce a local-only diagnostic, with honest remote-check uncertainty."""
    target = castctl.validate_manual_target(receiver)
    if not _lan_source(target):
        raise ValueError("Network check requires a private RFC1918 Cast IPv4 address")
    source, route_error = route_source(target, socket_factory=socket_factory)
    name = interface_name(
        target, source, os_name=os_name or platform.system(), run=run,
    )
    port_state = check_receiver_port(target, connect=connect) if source else "not_checked"
    port = active_port()
    local_health = check_local_hls(open_url=open_url, port=port)
    # Only private interface addresses should be recommended for access from
    # another LAN machine. A public/loopback result must not yield a link.
    private = bool(source and _lan_source(source))
    second_host_url = (
        f"http://{source}:{port}{HEALTH_PATH}" if source and private else None
    )
    return {
        "receiver_ip": target,
        "receiver_cast_tcp_port": CAST_PORT,
        "receiver_cast_port": port_state,
        "selected_source_ipv4": source,
        "selected_interface": name,
        "route_error": route_error,
        "vpn_interface_suspected": bool(_VPN_INTERFACE.match(name)) if name else None,
        "route_warning": address_policy.route_warning(name) if name else None,
        "local_hls_health": local_health,
        "second_host_health_url": second_host_url,
        "inbound_hls_reachability": "not_verified_from_second_host",
        "firewall_diagnosis": "unknown_without_second_host_test",
        "interpretation": [
            "A selected source address means the OS has a route, not that the receiver is reachable.",
            "Cast TCP port failures may mean receiver offline, VPN isolation, or firewall; not proof of one cause.",
            "A healthy loopback HLS response does NOT prove the television can connect to this computer.",
            "Open second_host_health_url from another LAN device to test actual inbound media-port reachability.",
            "A VPN-like interface name is a diagnostic clue, not a confirmed VPN or firewall fault.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoothcast --network-check",
        description="Check local Cast route, port and HLS health without opening GTK",
    )
    parser.add_argument("receiver", help="Private IPv4 address of your Chromecast")
    args = parser.parse_args(argv)
    try:
        result = report(args.receiver)
    except ValueError as exc:
        print(f"SmoothCast network check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
