"""Opt-in GTK-agnostic adapter for local Cast route diagnostics.

Network probes run only after the user clicks the in-window control.
The worker never issues receiver playback commands or mutates cast ownership.
"""
from __future__ import annotations

import network_routes


def summary(result: dict) -> str:
    """Present measured local facts without inventing remote reachability."""
    source = result["selected_source_ipv4"] or "unavailable"
    interface = result["selected_interface"]
    route = f"{source} ({interface})" if interface else source
    link = result["second_host_health_url"]
    instructions = (
        f"While HLS is running, open from another LAN device: {link}"
        if link else "No private source IPv4 available for a second-device HLS check."
    )
    error = result["route_error"]
    return (
        f"Local route: {route}\n"
        f"Cast TCP 8009: {result['receiver_cast_port']} · "
        f"Local HLS: {result['local_hls_health']}\n"
        + (f"{error}\n" if error else "")
        + instructions + "\n"
        "Receiver-to-PC reachability and any firewall/VPN cause remain unverified."
    )


def start(window, run_async) -> None:
    """Coordinate the explicit check; publish only for the original selection."""
    if getattr(window, "_network_check_busy", False):
        return
    device = window._device()
    if window._dlna_renderer(device) is not None:
        window.toast("Connection check supports Google Cast receivers, not DLNA", error=True)
        return
    host = window._device_host(device)
    if not host:
        window.toast("Select a discovered or manual Cast receiver first", error=True)
        return

    window._network_check_busy = True
    window.network_check_button.set_sensitive(False)
    window.network_detail.set_text("Checking local route and HLS health…")

    def finished(message):
        window._network_check_busy = False
        if window._closing:
            return
        window.network_check_button.set_sensitive(True)
        window.network_detail.set_text(
            message if (window._device() == device and window._device_host(device) == host)
            else "Receiver changed; run the connection check again."
        )

    run_async(
        lambda: summary(network_routes.report(host)),
        done=finished,
        failed=lambda message: finished(f"Connection check failed: {message}"),
    )
