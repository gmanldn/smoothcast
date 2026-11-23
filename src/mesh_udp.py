"""Real clock and UDP sockets for the mesh (ticket #396).

``MeshLoop`` is one thread that owns timers and socket readers, so every mesh
callback runs serially on it (no locks inside mesh layers). ``UdpTransport``
implements ``mesh_ports.Transport`` for datagrams on one private LAN interface:
it never binds all interfaces, joins the presence multicast group on that
interface only, and drops nothing silently that could hide a bug (errors are
counted). Request/response (pinned HTTPS sync) arrives with #398 and #358;
``request`` reports ``"unsupported"`` until then.

GTK-free. The simulator in ``tests/mesh_sim.py`` stands in for both in tests.
"""
from __future__ import annotations

from collections.abc import Callable
import heapq
import itertools
import selectors
import socket
import struct
import sys
import threading
import time

import mesh_beacon
import mesh_model
from mesh_ports import Datagram

GROUP = "239.255.83.67"
READ_SIZE = 1024                   # larger than MAX_DATAGRAM so oversize is detectable


class _Timer:
    __slots__ = ("cancelled",)

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class MeshLoop:
    """Serial event loop: timers plus socket readers on a single daemon thread."""

    def __init__(self, name: str = "smoothcast-mesh",
                 on_error: Callable[[BaseException], None] | None = None) -> None:
        self._name = name
        self._on_error = on_error
        self._lock = threading.Lock()
        self._heap: list[tuple[float, int, _Timer, Callable[[], None]]] = []
        self._counter = itertools.count()
        self._selector = selectors.DefaultSelector()
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)
        self._selector.register(self._wake_r, selectors.EVENT_READ, None)
        self._thread: threading.Thread | None = None
        self._running = False
        self.errors = 0

    # -- Clock port ----------------------------------------------------------
    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer()
        with self._lock:
            heapq.heappush(self._heap, (time.monotonic() + max(0.0, delay),
                                        next(self._counter), timer, callback))
        self._wake()
        return timer

    def call_soon_threadsafe(self, callback: Callable[[], None]) -> None:
        self.call_later(0.0, callback)

    # -- readers ---------------------------------------------------------------
    def add_reader(self, sock: socket.socket, callback: Callable[[], None]) -> None:
        sock.setblocking(False)
        self._selector.register(sock, selectors.EVENT_READ, callback)
        self._wake()

    def remove_reader(self, sock: socket.socket) -> None:
        try:
            self._selector.unregister(sock)
        except (KeyError, ValueError, OSError):
            pass

    # -- lifecycle ---------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the thread and release the wake pipe. Idempotent."""
        thread, self._thread = self._thread, None
        self._running = False
        if thread is not None:
            self._wake()
            if thread is not threading.current_thread():
                thread.join(timeout)
        for sock in (self._wake_r, self._wake_w):
            try:
                self._selector.unregister(sock)
            except (KeyError, ValueError, OSError):
                pass
            sock.close()
        try:
            self._selector.close()
        except OSError:
            pass

    def _wake(self) -> None:
        try:
            self._wake_w.send(b"x")
        except (BlockingIOError, OSError):
            pass

    def _run(self) -> None:
        while self._running:
            with self._lock:
                while self._heap and self._heap[0][2].cancelled:
                    heapq.heappop(self._heap)
                timeout = (max(0.0, self._heap[0][0] - time.monotonic())
                           if self._heap else 1.0)
            try:
                events = self._selector.select(min(timeout, 1.0))
            except (OSError, ValueError):
                if not self._running:
                    return
                continue
            for key, _mask in events:
                if key.data is None:
                    try:
                        self._wake_r.recv(4096)
                    except (BlockingIOError, OSError):
                        pass
                    continue
                self._guard(key.data)
            now = time.monotonic()
            while True:
                with self._lock:
                    if not self._heap or self._heap[0][0] > now:
                        break
                    _when, _n, timer, callback = heapq.heappop(self._heap)
                if not timer.cancelled:
                    self._guard(callback)

    def _guard(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:                 # one bad callback never stops the loop
            self.errors += 1
            if self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    pass


def _split(address: str, default_port: int) -> tuple[str, int]:
    host, _, port = address.partition(":")
    return host, int(port) if port else default_port


class UdpTransport:
    """Datagram transport on one private IPv4 interface.

    ``stand_in_peers`` replaces multicast with unicast to a fixed list of
    ``ip:port`` strings. It exists for loopback tests on machines without a
    multicast-capable loopback; production passes ``multicast=True``.
    """

    def __init__(self, loop: MeshLoop, bind_ip: str, port: int = mesh_beacon.DEFAULT_PORT,
                 *, multicast: bool = True, group: str = GROUP,
                 stand_in_peers: list[str] | None = None) -> None:
        if not mesh_model.is_lan_address(bind_ip):
            raise ValueError("bind_ip must be a private LAN IPv4 address")
        self._loop = loop
        self._ip = bind_ip
        self._port = port
        self._group = group
        self._multicast = multicast
        self.stand_in_peers = list(stand_in_peers or [])
        self._datagram_handler: Callable[[Datagram], None] | None = None
        self.send_errors = 0
        self.sent_bytes = 0
        self.recv_bytes = 0
        self.closed = False
        self._unicast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._group_sock: socket.socket | None = None
        try:
            self._unicast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT") and multicast:
                self._unicast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self._unicast.bind((bind_ip, port))
            self._port = self._unicast.getsockname()[1]
            if multicast:
                self._setup_multicast()
        except OSError:
            self._close_sockets()
            raise
        self._loop.add_reader(self._unicast, lambda: self._read(self._unicast, False))
        if self._group_sock is not None:
            gsock = self._group_sock
            self._loop.add_reader(gsock, lambda: self._read(gsock, True))

    def _setup_multicast(self) -> None:
        iface = socket.inet_aton(self._ip)
        self._unicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, iface)
        self._unicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        self._unicast.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        group_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            group_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                group_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            # POSIX: bind the group address so only this group's traffic arrives.
            # Windows cannot bind a multicast address, so it binds the interface.
            group_sock.bind((self._ip if sys.platform.startswith("win") else self._group,
                             self._port))
            membership = struct.pack("4s4s", socket.inet_aton(self._group), iface)
            group_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError:
            group_sock.close()
            raise
        self._group_sock = group_sock

    # -- Transport port ---------------------------------------------------------
    @property
    def address(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    def set_datagram_handler(self, handler: Callable[[Datagram], None] | None) -> None:
        self._datagram_handler = handler

    def set_request_handler(self, handler: Callable[[str, bytes], bytes | None] | None) -> None:
        return None                                  # arrives with #398

    def send_multicast(self, payload: bytes) -> None:
        if self.closed:
            return
        if self._multicast:
            self._send(payload, (self._group, self._port))
        for peer in self.stand_in_peers:
            self._send(payload, _split(peer, self._port))

    def send_unicast(self, address: str, payload: bytes) -> None:
        if self.closed:
            return
        try:
            target = _split(address, self._port)
        except ValueError:
            self.send_errors += 1
            return
        if mesh_model.is_lan_address(target[0]):
            self._send(payload, target)
        else:
            self.send_errors += 1                    # public targets are refused

    def request(self, address: str, payload: bytes,
                callback: Callable[[bytes | None, str | None], None],
                timeout: float = 3.0) -> None:
        self._loop.call_later(0.0, lambda: callback(None, "unsupported"))

    def _send(self, payload: bytes, target: tuple[str, int]) -> None:
        try:
            self._unicast.sendto(payload, target)
            self.sent_bytes += len(payload)
        except OSError:
            self.send_errors += 1

    def _read(self, sock: socket.socket, multicast: bool) -> None:
        for _ in range(64):                          # bound work per wakeup
            if self.closed:
                return
            try:
                data, (source, _port) = sock.recvfrom(READ_SIZE)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            self.recv_bytes += len(data)
            handler = self._datagram_handler
            if handler is not None:
                handler(Datagram(source, data, multicast))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._datagram_handler = None
        self._loop.remove_reader(self._unicast)
        if self._group_sock is not None:
            self._loop.remove_reader(self._group_sock)
        self._close_sockets()

    def _close_sockets(self) -> None:
        for sock in (self._unicast, self._group_sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
