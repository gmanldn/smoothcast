"""Narrow ports the mesh core is written against (ticket #395, "M2").

Production code supplies a real clock and real sockets; the deterministic
simulator in ``tests/mesh_sim.py`` supplies a virtual clock and a simulated
network. Mesh layers (beacon, membership, replication, ...) import *only*
these protocols, never ``socket``, ``threading.Timer`` or ``time`` directly,
which is what makes them testable in milliseconds without flakiness.

GTK-free and dependency-free. Design: docs/MESH_DESIGN.md.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TimerHandle(Protocol):
    def cancel(self) -> None:
        """Stop the timer; harmless if it already fired or was cancelled."""


@runtime_checkable
class Clock(Protocol):
    """Time source and scheduler. Callbacks run one at a time on the mesh loop."""

    def monotonic(self) -> float:
        """Seconds on a clock that never goes backwards (may pause in suspend)."""

    def wall(self) -> float:
        """Seconds since the Unix epoch; may jump (NTP, sleep/wake). Never compare
        wall times across machines."""

    def call_later(self, delay: float, callback: Callable[[], None]) -> TimerHandle:
        """Run *callback* after *delay* seconds."""


@dataclass(frozen=True)
class Datagram:
    """One received datagram. ``src`` is the observed source address."""

    src: str
    payload: bytes
    multicast: bool = False


DatagramHandler = Callable[[Datagram], None]
#: Answer a request: ``(src, payload) -> reply bytes`` or ``None`` for no answer.
RequestHandler = Callable[[str, bytes], "bytes | None"]
#: Reply callback: ``(reply, error)``. Exactly one of the two is ``None``.
ReplyCallback = Callable[["bytes | None", "str | None"], None]


@runtime_checkable
class Transport(Protocol):
    """Datagrams (presence) plus request/response (state sync) for one interface."""

    @property
    def address(self) -> str:
        """The local private IPv4 address this transport is bound to."""

    def set_datagram_handler(self, handler: DatagramHandler | None) -> None: ...

    def set_request_handler(self, handler: RequestHandler | None) -> None: ...

    def send_multicast(self, payload: bytes) -> None:
        """Best effort, unreliable; delivered to every reachable listener."""

    def send_unicast(self, address: str, payload: bytes) -> None:
        """Best effort, unreliable datagram to one address."""

    def request(self, address: str, payload: bytes, callback: ReplyCallback,
                timeout: float = 3.0) -> None:
        """Reliable request/response (stands in for pinned HTTPS).

        *callback* is invoked exactly once: with the reply, or with an error
        string such as ``"timeout"`` or ``"unreachable"``.
        """

    def close(self) -> None:
        """Release the socket; idempotent. No handler runs after this returns."""
