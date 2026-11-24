"""Fail-closed demo-mode gate and loopback-only network guard (#454/#523).

GTK-free. Demo mode is active only when ``SMOOTHCAST_DEMO=1`` **and** a
capability token written by :mod:`demo_runtime` into the profile's private
``XDG_RUNTIME_DIR`` matches ``SMOOTHCAST_DEMO_TOKEN``; a stray environment
variable in a developer shell cannot switch it on.

When active, :func:`install_network_guard` makes every socket connect, send,
bind and name lookup that is not loopback raise :class:`DemoModeError`, so a
forgotten discovery path fails closed instead of reaching a real receiver.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from pathlib import Path
import socket
from typing import Any, Mapping

ENV = "SMOOTHCAST_DEMO"
TOKEN_ENV = "SMOOTHCAST_DEMO_TOKEN"
MARKER = ".smoothcast-demo-token"
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}
_installed = False


class DemoModeError(OSError):
    """A network operation outside loopback was refused in demo mode."""


def active(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    if values.get(ENV) != "1":
        return False
    token = values.get(TOKEN_ENV, "")
    runtime = values.get("XDG_RUNTIME_DIR", "")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token) or not runtime:
        return False
    marker = Path(runtime) / MARKER
    try:
        if marker.is_symlink() or not marker.is_file():
            return False
        return hmac.compare_digest(marker.read_text(encoding="ascii"), token)
    except (OSError, UnicodeError, ValueError):
        return False


def is_loopback_host(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    name = host.strip().rstrip(".").lower()
    if name in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name.split("%")[0]).is_loopback
    except ValueError:
        return False


def assert_loopback(host: object) -> None:
    if not is_loopback_host(host):
        raise DemoModeError("demo mode only talks to loopback; refused a network address")


def _address_host(address: Any) -> object:
    return address[0] if isinstance(address, (tuple, list)) and address else address


def install_network_guard() -> bool:
    """Patch socket so non-loopback traffic raises. Idempotent; no-op unless active()."""
    global _installed
    if _installed or not active():
        return _installed
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_bind = socket.socket.bind
    original_create = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def checked(address: Any) -> None:
        if isinstance(address, (str, bytes)) and not isinstance(address, tuple):
            return  # AF_UNIX path
        assert_loopback(_address_host(address))

    def connect(self, address):
        checked(address)
        return original_connect(self, address)

    def connect_ex(self, address):
        checked(address)
        return original_connect_ex(self, address)

    def sendto(self, data, *args):
        checked(args[-1])
        return original_sendto(self, data, *args)

    def bind(self, address):
        checked(address)  # "" / 0.0.0.0 would listen on the LAN: refused
        return original_bind(self, address)

    def create_connection(address, *args, **kwargs):
        checked(address)
        return original_create(address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_loopback_host(host):
            raise DemoModeError("demo mode refuses name lookups outside loopback")
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socket.sendto = sendto  # type: ignore[method-assign]
    socket.socket.bind = bind  # type: ignore[method-assign]
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
    _installed = True
    return True


def demo_target() -> tuple[str, int, str]:
    """(host, port, name) of the profile's one fake receiver; loopback enforced."""
    import json
    import demo_runtime
    base = Path(os.environ.get("XDG_CONFIG_HOME") or "")
    config = json.loads((base / "cast-control" / "config.json").read_text(encoding="utf-8"))
    for target in config.get("cast_targets") or []:
        host = str(target.get("host", ""))
        assert_loopback(host)
        return host, int(target["port"]), str(target.get("name") or demo_runtime.DEMO_DEVICE_NAME)
    raise DemoModeError("demo profile has no receiver")


def backend():
    """PyChromecast backend that only ever reaches the profile's loopback receiver."""
    try:
        import pychromecast
    except ImportError as exc:
        raise DemoModeError("demo mode needs PyChromecast installed") from exc
    from pychromecast_backend import PyChromecastBackend

    host, port, name = demo_target()

    def connect_from_host(info, *args, **kwargs):
        assert_loopback(info[0])
        return pychromecast.get_chromecast_from_host(info, *args, **kwargs)

    def discover(*, callback, **_ignored):
        import uuid
        cast = connect_from_host((host, port, uuid.uuid5(uuid.NAMESPACE_URL, f"demo:{host}:{port}"),
                                  "SmoothCast Demo", name), tries=1, retry_wait=0.1, timeout=5)
        callback(cast)
        return type("Browser", (), {"stop_discovery": staticmethod(lambda: None)})()

    return PyChromecastBackend(discover=discover, connect_from_host=connect_from_host)
