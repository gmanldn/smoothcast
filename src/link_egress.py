"""Public-only egress for isolated link downloads (#588).

``is_public_address`` is the single policy: only routable, unicast, public
addresses pass. It rejects loopback, private, link-local (incl. the cloud
metadata address 169.254.169.254), CGNAT, ULA, multicast, reserved,
unspecified, IPv4-mapped/compatible IPv6 wrappers of any of those, NAT64,
6to4 and Teredo (which can smuggle a private IPv4), for IPv4 and IPv6.

``EgressProxy`` enforces it on the wire: an HTTP ``CONNECT``-only proxy that
resolves the name itself, requires EVERY answer to be public (a mixed answer
is a rebinding attempt), then connects to the already-checked IP, so a second
lookup can never swap in a private address. Each new connection, including one
following a redirect, is checked again. Ports, concurrency, per-tunnel bytes,
idle time and total time are bounded. No inbound port is ever opened (the proxy
listens on a private UNIX socket). GTK-free; stdlib only.
"""
from __future__ import annotations

from collections.abc import Callable
import ipaddress
import os
from pathlib import Path
import select
import socket
import threading
import time

ALLOWED_PORTS = frozenset({80, 443})
MAX_TUNNELS = 16
MAX_TUNNEL_BYTES = 2 * 1024**3
IDLE_SECONDS = 60.0
TOTAL_SECONDS = 1800.0
CONNECT_SECONDS = 10.0
MAX_HEADER = 8192
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")
_TEREDO = ipaddress.ip_network("2001::/32")
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")


def is_public_address(value: object) -> bool:
    try:
        ip = ipaddress.ip_address(value if isinstance(value, str) else "")
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_address(str(ip.ipv4_mapped))
        if any(ip in net for net in (_NAT64, _NAT64_LOCAL, _TEREDO, _SIX_TO_FOUR)):
            return False
    return bool(ip.is_global and not ip.is_multicast and not ip.is_private
                and not ip.is_loopback and not ip.is_link_local and not ip.is_reserved
                and not ip.is_unspecified)


class EgressDenied(PermissionError):
    """The destination is not allowed; nothing was connected."""


def resolve_public(host: str, port: int, resolver: Callable = socket.getaddrinfo) -> list[tuple[int, str]]:
    """All answers for *host*, only if every one is public (else EgressDenied)."""
    if not isinstance(host, str) or not host or len(host) > 253 or any(c in host for c in " \t\r\n/\\@"):
        raise EgressDenied("invalid destination")
    host = host.strip("[]")
    if port not in ALLOWED_PORTS:
        raise EgressDenied("port not allowed")
    try:
        answers = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EgressDenied("name did not resolve") from exc
    out = []
    for family, _kind, _proto, _canon, sockaddr in answers:
        address = sockaddr[0].split("%")[0]
        if not is_public_address(address):
            raise EgressDenied("destination resolves to a non-public address")
        out.append((family, address))
    if not out:
        raise EgressDenied("name did not resolve")
    return out


class EgressProxy:
    def __init__(self, socket_path: str | Path, *, resolver: Callable = socket.getaddrinfo,
                 connector: Callable[[int, str, int], socket.socket] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 max_bytes: int = MAX_TUNNEL_BYTES) -> None:
        self.path = str(socket_path)
        self._resolver, self._clock, self._max_bytes = resolver, clock, max_bytes
        self._connector = connector or self._connect
        self._slots = threading.BoundedSemaphore(MAX_TUNNELS)
        self._stop = threading.Event()
        self.denied = 0
        self.tunnels = 0
        if os.path.exists(self.path):
            os.unlink(self.path)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        os.chmod(self.path, 0o600)
        self._server.listen(16)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, name="smoothcast-egress", daemon=True)
        self._thread.start()

    @staticmethod
    def _connect(family: int, address: str, port: int) -> socket.socket:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_SECONDS)
        try:
            sock.connect((address, port))
        except OSError:
            sock.close()
            raise
        return sock

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._server.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _reply(self, client: socket.socket, status: str) -> None:
        try:
            client.sendall(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
        except OSError:
            pass

    def _handle(self, client: socket.socket) -> None:
        client.settimeout(10)
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(2048)
                if not chunk or len(data) + len(chunk) > MAX_HEADER:
                    return self._reply(client, "400 Bad Request")
                data += chunk
            head, _, leftover = data.partition(b"\r\n\r\n")
            parts = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
            if len(parts) != 3 or parts[0] != "CONNECT":
                return self._reply(client, "405 Method Not Allowed")
            host, _, port_text = parts[1].rpartition(":")
            if not port_text.isdigit():
                return self._reply(client, "400 Bad Request")
            try:
                targets = resolve_public(host, int(port_text), self._resolver)
            except EgressDenied:
                self.denied += 1
                return self._reply(client, "403 Forbidden")
            if not self._slots.acquire(blocking=False):
                return self._reply(client, "503 Service Unavailable")
            try:
                upstream = None
                for family, address in targets:  # pinned: the IPs we just verified
                    try:
                        upstream = self._connector(family, address, int(port_text))
                        break
                    except OSError:
                        continue
                if upstream is None:
                    return self._reply(client, "502 Bad Gateway")
                with upstream:
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self.tunnels += 1
                    if leftover:
                        upstream.sendall(leftover)
                    self._pump(client, upstream)
            finally:
                self._slots.release()
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _pump(self, a: socket.socket, b: socket.socket) -> None:
        start = last = self._clock()
        moved = 0
        a.settimeout(None)
        b.settimeout(None)
        while not self._stop.is_set():
            now = self._clock()
            if now - last > IDLE_SECONDS or now - start > TOTAL_SECONDS or moved > self._max_bytes:
                return
            ready, _, _ = select.select([a, b], [], [], 1.0)
            for source in ready:
                chunk = source.recv(65536)
                if not chunk:
                    return
                moved += len(chunk)
                (b if source is a else a).sendall(chunk)
                last = self._clock()
