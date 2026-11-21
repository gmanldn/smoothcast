"""Deterministic discrete-event network simulator for the SmoothCast mesh (#395).

Everything runs on a virtual clock in integer milliseconds with a seeded RNG, so
a scenario that takes minutes of "network time" runs in milliseconds and the same
seed always produces the identical event log. No sockets, threads or sleeps.

Pieces
------
* :class:`SimClock` / :class:`NodeClock` - virtual time; per-node wall-clock skew
  and suspend/resume (monotonic time pauses while a node sleeps; wall time jumps).
* :class:`SimNetwork` / :class:`SimTransport` - implements ``mesh_ports.Transport``
  with latency, jitter, loss, optional bandwidth, partitions, multicast on/off,
  node up/down, IP change and byte accounting.
* :class:`SimWorld` - scenario helpers (``add``, ``stop``, ``sleep``, ``wake``,
  ``change_ip``, ``partition``, ``heal``...), convergence measurement, budgets,
  invariants and seeded random scenarios.
* :class:`ToyGossipNode` - a deliberately simple reference node that proves the
  harness can both pass and fail a budget. Real mesh layers plug in through the
  same ``NodeUnderTest`` factory.

Limits of the model (documented so nobody over-trusts it): links are independent
(no shared-medium contention), RPC loss is modelled as retransmission delay, and
CPU cost is not simulated. Real-network qualification stays in #208.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
import heapq
import random
import sys
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_model as mm
from mesh_ports import Datagram

UDP_OVERHEAD = 28          # IPv4 + UDP header bytes added to every datagram
RPC_OVERHEAD = 220         # rough TLS/HTTP framing per request or reply
RETRANSMIT_S = 0.2         # delay added per lost RPC segment

# Budgets from docs/MESH_DESIGN.md. egress = bytes a node *sends* per second.
BUDGETS: dict[str, float] = {
    "join_typical_s": 1.0,
    "join_p99_s": 3.0,
    "leave_clean_s": 0.5,
    "silent_loss_s": 7.0,
    "target_visible_s": 3.0,
    "egress_bytes_per_s_at_20_nodes": 2048.0,
}


class BudgetExceeded(AssertionError):
    pass


# ---------------------------------------------------------------------------
# Virtual time


class _Timer:
    __slots__ = ("cancelled",)

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class SimClock:
    """Global virtual clock with a deterministic event queue."""

    def __init__(self, wall_epoch: float = 1_700_000_000.0) -> None:
        self.now_ms = 0
        self._wall_epoch = wall_epoch
        self._queue: list[tuple[int, int, _Timer, Callable[[], None]]] = []
        self._seq = 0
        self.events_run = 0

    def monotonic(self) -> float:
        return self.now_ms / 1000.0

    def wall(self) -> float:
        return self._wall_epoch + self.now_ms / 1000.0

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer()
        self._seq += 1
        heapq.heappush(self._queue, (self.now_ms + max(0, round(delay * 1000)),
                                     self._seq, timer, callback))
        return timer

    def advance_ms(self, ms: int) -> None:
        target = self.now_ms + max(0, int(ms))
        while self._queue and self._queue[0][0] <= target:
            when, _seq, timer, callback = heapq.heappop(self._queue)
            self.now_ms = when
            if not timer.cancelled:
                self.events_run += 1
                callback()
        self.now_ms = target

    def advance(self, seconds: float) -> None:
        self.advance_ms(round(seconds * 1000))

    @property
    def pending(self) -> int:
        return sum(1 for item in self._queue if not item[2].cancelled)


class NodeClock:
    """One node's view of time: wall skew, and monotonic time that pauses in sleep."""

    def __init__(self, base: SimClock, skew_s: float = 0.0) -> None:
        self._base = base
        self.skew_s = skew_s
        self._frozen_at: float | None = None
        self._paused_total = 0.0
        self._held: list[tuple[_Timer, Callable[[], None]]] = []
        self.suspended = False

    def monotonic(self) -> float:
        now = self._frozen_at if self._frozen_at is not None else self._base.monotonic()
        return now - self._paused_total

    def wall(self) -> float:
        return self._base.wall() + self.skew_s

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer()

        def fire() -> None:
            if timer.cancelled:
                return
            if self.suspended:
                self._held.append((timer, callback))   # overdue timers run on wake
            else:
                callback()

        self._base.call_later(delay, fire)
        return timer

    def suspend(self) -> None:
        if not self.suspended:
            self.suspended = True
            self._frozen_at = self._base.monotonic()

    def resume(self) -> None:
        if self.suspended:
            assert self._frozen_at is not None
            self._paused_total += self._base.monotonic() - self._frozen_at
            self._frozen_at = None
            self.suspended = False
            held, self._held = self._held, []
            for timer, callback in held:
                if not timer.cancelled:
                    callback()


# ---------------------------------------------------------------------------
# Network


@dataclass
class LinkProfile:
    latency_ms: int = 2
    jitter_ms: int = 1
    loss: float = 0.0
    bandwidth_bps: int | None = None


@dataclass
class NodeStats:
    sent_bytes: int = 0
    recv_bytes: int = 0
    sent_msgs: int = 0
    recv_msgs: int = 0
    sent_by_second: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    recv_by_second: dict[int, int] = field(default_factory=lambda: defaultdict(int))


class SimTransport:
    """``mesh_ports.Transport`` for one simulated interface."""

    def __init__(self, network: SimNetwork, address: str) -> None:
        self._net = network
        self._address = address
        self._datagram_handler: Callable[[Datagram], None] | None = None
        self._request_handler: Callable[[str, bytes], bytes | None] | None = None
        self.closed = False

    @property
    def address(self) -> str:
        return self._address

    def set_datagram_handler(self, handler: Callable[[Datagram], None] | None) -> None:
        self._datagram_handler = handler

    def set_request_handler(self, handler: Callable[[str, bytes], bytes | None] | None) -> None:
        self._request_handler = handler

    def send_multicast(self, payload: bytes) -> None:
        if not self.closed:
            self._net._send_datagram(self, None, bytes(payload))

    def send_unicast(self, address: str, payload: bytes) -> None:
        if not self.closed:
            self._net._send_datagram(self, address, bytes(payload))

    def request(self, address: str, payload: bytes,
                callback: Callable[[bytes | None, str | None], None],
                timeout: float = 3.0) -> None:
        if self.closed:
            callback(None, "closed")
            return
        self._net._request(self, address, bytes(payload), callback, timeout)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._datagram_handler = None
            self._request_handler = None
            self._net._detach(self)


class SimNetwork:
    """One broadcast domain with configurable faults."""

    def __init__(self, clock: SimClock, rng: random.Random) -> None:
        self.clock = clock
        self.rng = rng
        self.default_link = LinkProfile()
        self.multicast_enabled = True
        self.multicast_loopback = True      # like IP_MULTICAST_LOOP: senders hear themselves
        self._links: dict[tuple[str, str], LinkProfile] = {}
        self._transports: dict[str, SimTransport] = {}
        self._offline: set[str] = set()
        self._groups: list[set[str]] | None = None
        self.stats: dict[str, NodeStats] = defaultdict(NodeStats)
        self.log: list[tuple[int, str, str, str, int]] = []
        self.log_enabled = True

    # -- topology -----------------------------------------------------------
    def attach(self, address: str) -> SimTransport:
        if address in self._transports:
            raise ValueError(f"address {address} already attached")
        transport = SimTransport(self, address)
        self._transports[address] = transport
        return transport

    def _detach(self, transport: SimTransport) -> None:
        if self._transports.get(transport.address) is transport:
            del self._transports[transport.address]

    def rebind(self, transport: SimTransport, new_address: str) -> None:
        """Simulate an IP change (Wi-Fi roam, DHCP renew): same socket, new address."""
        if new_address in self._transports:
            raise ValueError(f"address {new_address} already attached")
        del self._transports[transport._address]
        transport._address = new_address
        self._transports[new_address] = transport

    def set_link(self, a: str, b: str, profile: LinkProfile) -> None:
        self._links[(a, b)] = profile
        self._links[(b, a)] = profile

    def set_online(self, address: str, online: bool) -> None:
        (self._offline.discard if online else self._offline.add)(address)

    def partition(self, *groups: list[str] | set[str]) -> None:
        self._groups = [set(group) for group in groups]

    def heal(self) -> None:
        self._groups = None

    def reachable(self, src: str, dst: str, *, in_flight: bool = False) -> bool:
        """Can *src* reach *dst* now? A packet already in flight survives its
        sender going offline (a clean goodbye is sent just before shutdown)."""
        if (src in self._offline and not in_flight) or dst in self._offline \
                or dst not in self._transports:
            return False
        if self._groups is None:
            return True
        return any(src in group and dst in group for group in self._groups)

    # -- delivery -----------------------------------------------------------
    def _profile(self, src: str, dst: str) -> LinkProfile:
        return self._links.get((src, dst), self.default_link)

    def _delay_ms(self, profile: LinkProfile, size: int) -> int:
        jitter = self.rng.randint(0, profile.jitter_ms) if profile.jitter_ms else 0
        serial = 0 if not profile.bandwidth_bps else round(size * 8000 / profile.bandwidth_bps)
        return profile.latency_ms + jitter + serial

    def _account_send(self, src: str, size: int) -> None:
        stats = self.stats[src]
        stats.sent_bytes += size
        stats.sent_msgs += 1
        stats.sent_by_second[self.clock.now_ms // 1000] += size

    def _account_recv(self, dst: str, size: int) -> None:
        stats = self.stats[dst]
        stats.recv_bytes += size
        stats.recv_msgs += 1
        stats.recv_by_second[self.clock.now_ms // 1000] += size

    def _note(self, kind: str, src: str, dst: str, size: int) -> None:
        if self.log_enabled:
            self.log.append((self.clock.now_ms, kind, src, dst, size))

    def _send_datagram(self, sender: SimTransport, dst: str | None, payload: bytes) -> None:
        src = sender.address
        if src in self._offline:
            return
        size = len(payload) + UDP_OVERHEAD
        self._account_send(src, size)                  # multicast counts once
        if dst is None:
            if not self.multicast_enabled:
                self._note("mcast-blocked", src, "*", size)
                return
            targets = [addr for addr in sorted(self._transports)
                       if addr != src or self.multicast_loopback]
        else:
            targets = [dst]
        for target in targets:
            if not self.reachable(src, target):
                self._note("drop-unreachable", src, target, size)
                continue
            profile = self._profile(src, target)
            if profile.loss and self.rng.random() < profile.loss:
                self._note("drop-loss", src, target, size)
                continue
            delay = self._delay_ms(profile, size)
            self._note("send", src, target, size)
            self.clock.call_later(delay / 1000.0, self._deliver(
                src, target, payload, dst is None, size))

    def _deliver(self, src: str, dst: str, payload: bytes, multicast: bool,
                 size: int) -> Callable[[], None]:
        def run() -> None:
            transport = self._transports.get(dst)
            if transport is None or not self.reachable(src, dst, in_flight=True):
                return
            self._account_recv(dst, size)
            handler = transport._datagram_handler
            if handler is not None:
                handler(Datagram(src, payload, multicast))
        return run

    def _request(self, sender: SimTransport, dst: str, payload: bytes,
                 callback: Callable[[bytes | None, str | None], None],
                 timeout: float) -> None:
        src = sender.address
        done = {"v": False}

        def finish(reply: bytes | None, error: str | None) -> None:
            if not done["v"]:
                done["v"] = True
                callback(reply, error)

        timer = self.clock.call_later(timeout, lambda: finish(None, "timeout"))

        def settle(reply: bytes | None, error: str | None) -> None:
            timer.cancel()
            finish(reply, error)

        if src in self._offline or not self.reachable(src, dst):
            return                                      # silence until the timeout
        profile = self._profile(src, dst)
        size = len(payload) + RPC_OVERHEAD
        self._account_send(src, size)
        self._note("rpc", src, dst, size)
        delay = self._delay_ms(profile, size) + self._retransmits(profile) * round(
            RETRANSMIT_S * 1000)

        def arrive() -> None:
            target = self._transports.get(dst)
            if target is None or not self.reachable(src, dst, in_flight=True):
                return
            self._account_recv(dst, size)
            handler = target._request_handler
            reply = handler(src, payload) if handler is not None else None
            if reply is None:
                self.clock.call_later(0.0, lambda: settle(None, "refused"))
                return
            reply_size = len(reply) + RPC_OVERHEAD
            self._account_send(dst, reply_size)
            back = self._delay_ms(profile, reply_size) + self._retransmits(profile) * round(
                RETRANSMIT_S * 1000)

            def returned() -> None:
                if not self.reachable(dst, src, in_flight=True):
                    return
                self._account_recv(src, reply_size)
                settle(reply, None)
            self.clock.call_later(back / 1000.0, returned)

        self.clock.call_later(delay / 1000.0, arrive)

    def _retransmits(self, profile: LinkProfile) -> int:
        count = 0
        while profile.loss and count < 8 and self.rng.random() < profile.loss:
            count += 1
        return count

    # -- measurements -------------------------------------------------------
    def egress_bytes_per_s(self, address: str, window_s: int, end_s: int | None = None) -> float:
        end = self.clock.now_ms // 1000 if end_s is None else end_s
        buckets = self.stats[address].sent_by_second
        return sum(buckets.get(sec, 0) for sec in range(end - window_s, end)) / window_s

    def ingress_bytes_per_s(self, address: str, window_s: int, end_s: int | None = None) -> float:
        end = self.clock.now_ms // 1000 if end_s is None else end_s
        buckets = self.stats[address].recv_by_second
        return sum(buckets.get(sec, 0) for sec in range(end - window_s, end)) / window_s


# ---------------------------------------------------------------------------
# Nodes under test


class NodeUnderTest(Protocol):
    """What a mesh implementation exposes so the harness can judge it."""

    node_id: str

    def start(self) -> None: ...

    def stop(self, clean: bool) -> None: ...

    def local_key(self) -> tuple[str, int]:
        """``(boot_id, rev)`` of this node's own record."""

    def records(self) -> dict[str, tuple[str, int]]:
        """Digest of every *alive* node this node currently knows (incl. itself)."""

    def target_ids(self) -> set[str]:
        """Target ids present in any alive record."""

    def add_target(self, target: mm.TargetObservation) -> None:
        """Publish a new local target observation (bumps the local rev)."""


NodeFactory = Callable[..., NodeUnderTest]


class ToyGossipNode:
    """Reference node: multicast the whole record every heartbeat, no forwarding.

    Deliberately naive. It converges on a healthy multicast LAN, which lets the
    harness prove it can pass budgets, and it fails on blocked multicast or tight
    budgets, which proves the harness can fail them too.
    """

    ALIVE_FOR = 3.5

    def __init__(self, *, node_id: str, boot_id: str, name: str, clock: Any,
                 transport: Any, rng: random.Random, boot_epoch: int,
                 heartbeat: float = 1.0, burst: bool = True, reply: bool = True) -> None:
        self.node_id = node_id
        self.boot_id = boot_id
        self.name = name
        self._clock = clock
        self._transport = transport
        self._rng = rng
        self._heartbeat = heartbeat
        self._burst = burst
        self._reply = reply
        self._rev = 1
        self._boot_epoch = boot_epoch
        self._targets: dict[str, mm.TargetObservation] = {}
        self._peers: dict[str, tuple[mm.NodeRecord, float]] = {}
        self._timers: list[Any] = []
        self._running = False

    # -- record -------------------------------------------------------------
    def _record(self) -> mm.NodeRecord:
        return mm.NodeRecord(
            node_id=self.node_id, boot_id=self.boot_id, name=self.name,
            version="1.2.0", rev=self._rev, boot_epoch=self._boot_epoch,
            targets=tuple(self._targets.values()),
            addresses=(self._transport.address,))

    def _payload(self, kind: bytes) -> bytes:
        return kind + b"\n" + mm.encode_record(mm.fit_record(self._record()))

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._running = True
        self._transport.set_datagram_handler(self._on_datagram)
        offsets = (0.0, 0.1, 0.3, 0.7, 1.5) if self._burst else (0.0,)
        for offset in offsets:
            self._timers.append(self._clock.call_later(offset, self._send_hello))
        self._timers.append(self._clock.call_later(
            self._heartbeat * (0.8 + 0.4 * self._rng.random()), self._beat))

    def stop(self, clean: bool) -> None:
        if not self._running:
            return
        if clean:
            self._transport.send_multicast(self._payload(b"BYE"))
            self._transport.send_multicast(self._payload(b"BYE"))
        self._running = False
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
        self._transport.close()

    def on_wake(self) -> None:
        self._send_hello()

    def on_address_changed(self) -> None:
        self._send_hello()

    def _beat(self) -> None:
        if not self._running:
            return
        self._transport.send_multicast(self._payload(b"BEAT"))
        self._timers.append(self._clock.call_later(
            self._heartbeat * (0.8 + 0.4 * self._rng.random()), self._beat))

    def _send_hello(self) -> None:
        if self._running:
            self._transport.send_multicast(self._payload(b"HELLO"))

    # -- receive ------------------------------------------------------------
    def _on_datagram(self, datagram: Datagram) -> None:
        kind, _, body = datagram.payload.partition(b"\n")
        try:
            record = mm.parse_record_bytes(body)
        except mm.MeshModelError:
            return
        if record.node_id == self.node_id:
            return
        now = self._clock.monotonic()
        if kind == b"BYE":
            known = self._peers.get(record.node_id)
            if known is not None and known[0].boot_id == record.boot_id:
                del self._peers[record.node_id]
            return
        known = self._peers.get(record.node_id)
        newer = (known is None
                 or (record.boot_epoch, record.rev) >= (known[0].boot_epoch, known[0].rev))
        if newer:
            self._peers[record.node_id] = (record, now)
        if kind == b"HELLO" and self._reply and known is None:
            self._transport.send_unicast(datagram.src, self._payload(b"BEAT"))

    # -- inspection ---------------------------------------------------------
    def _alive(self) -> dict[str, mm.NodeRecord]:
        now = self._clock.monotonic()
        return {node: record for node, (record, seen) in self._peers.items()
                if now - seen <= self.ALIVE_FOR}

    def local_key(self) -> tuple[str, int]:
        return (self.boot_id, self._rev)

    def records(self) -> dict[str, tuple[str, int]]:
        digest = mm.digest_of(self._alive().values())
        digest[self.node_id] = self.local_key()
        return digest

    def target_ids(self) -> set[str]:
        ids = set(self._targets)
        for record in self._alive().values():
            ids.update(target.id for target in record.targets)
        return ids

    def add_target(self, target: mm.TargetObservation) -> None:
        self._targets[target.id] = target
        self._rev += 1
        self._send_hello()


# ---------------------------------------------------------------------------
# The world


@dataclass
class NodeHandle:
    name: str
    node_id: str
    address: str
    clock: NodeClock
    transport: SimTransport | None = None
    node: NodeUnderTest | None = None
    boot_id: str = ""
    boots: int = 0
    state: str = "new"          # new | running | asleep | stopped

    @property
    def running(self) -> bool:
        return self.state == "running"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


class SimWorld:
    def __init__(self, seed: int = 0, factory: NodeFactory | None = None,
                 **node_kwargs: Any) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.clock = SimClock()
        self.net = SimNetwork(self.clock, random.Random(seed * 7919 + 1))
        self._factory: NodeFactory = factory or ToyGossipNode
        self._node_kwargs = node_kwargs
        self.nodes: dict[str, NodeHandle] = {}
        self._next_host = 10
        self.metrics: dict[str, list[float]] = defaultdict(list)

    # -- construction -------------------------------------------------------
    def _new_address(self) -> str:
        address = f"192.168.1.{self._next_host}"
        self._next_host += 1
        return address

    def _hex(self) -> str:
        return "%032x" % self.rng.getrandbits(128)

    def add(self, name: str | None = None, *, start: bool = True,
            skew_s: float = 0.0) -> NodeHandle:
        name = name or f"node{len(self.nodes) + 1}"
        handle = NodeHandle(name=name, node_id=self._hex(), address=self._new_address(),
                            clock=NodeClock(self.clock, skew_s))
        self.nodes[name] = handle
        if start:
            self.start(handle)
        return handle

    def start(self, handle: NodeHandle) -> None:
        """(Re)start: a new process with a fresh boot id on the same identity."""
        handle.boots += 1
        handle.boot_id = self._hex()
        self.net.set_online(handle.address, True)
        handle.clock.resume()
        handle.transport = self.net.attach(handle.address)
        handle.node = self._factory(
            node_id=handle.node_id, boot_id=handle.boot_id, name=handle.name,
            clock=handle.clock, transport=handle.transport,
            rng=random.Random(self.rng.getrandbits(64)),
            boot_epoch=int(self.clock.wall()) + handle.boots, **self._node_kwargs)
        handle.state = "running"
        handle.node.start()

    def join(self, count: int) -> list[NodeHandle]:
        return [self.add() for _ in range(count)]

    def running(self) -> list[NodeHandle]:
        return [h for h in self.nodes.values() if h.running]

    # -- faults -------------------------------------------------------------
    def stop(self, handle: NodeHandle, *, clean: bool = True) -> None:
        if handle.node is not None and handle.state in {"running", "asleep"}:
            if handle.state == "asleep":
                clean = False
            handle.node.stop(clean)
        if handle.state != "stopped":
            handle.state = "stopped"
            self.net.set_online(handle.address, False)

    def crash(self, handle: NodeHandle) -> None:
        self.stop(handle, clean=False)

    def restart(self, handle: NodeHandle, *, clean: bool = False) -> None:
        self.stop(handle, clean=clean)
        self.start(handle)

    def sleep(self, handle: NodeHandle) -> None:
        """Suspend the machine: no packets, timers frozen, monotonic clock paused."""
        if handle.running:
            handle.state = "asleep"
            handle.clock.suspend()
            self.net.set_online(handle.address, False)

    def wake(self, handle: NodeHandle) -> None:
        if handle.state == "asleep":
            self.net.set_online(handle.address, True)
            handle.state = "running"
            handle.clock.resume()
            hook = getattr(handle.node, "on_wake", None)
            if hook is not None:
                hook()

    def change_ip(self, handle: NodeHandle) -> str:
        new = self._new_address()
        old = handle.address
        assert handle.transport is not None
        self.net.rebind(handle.transport, new)
        self.net.set_online(new, handle.state == "running")
        self.net.set_online(old, False)
        handle.address = new
        hook = getattr(handle.node, "on_address_changed", None)
        if hook is not None and handle.running:
            hook()
        return new

    def partition(self, *groups: list[NodeHandle]) -> None:
        self.net.partition(*[{h.address for h in group} for group in groups])

    def heal(self) -> None:
        self.net.heal()

    def set_multicast(self, enabled: bool) -> None:
        self.net.multicast_enabled = enabled

    def set_loss(self, loss: float) -> None:
        self.net.default_link = LinkProfile(
            self.net.default_link.latency_ms, self.net.default_link.jitter_ms, loss,
            self.net.default_link.bandwidth_bps)

    def add_target(self, handle: NodeHandle, target_id: str, name: str = "TV",
                   kind: str = "cast") -> None:
        assert handle.node is not None
        handle.node.add_target(mm.TargetObservation(target_id, kind, name))

    # -- time ---------------------------------------------------------------
    def run(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def run_until(self, predicate: Callable[[], bool], timeout_s: float,
                  step_ms: int = 10) -> float | None:
        """Advance until *predicate* holds; return elapsed seconds, or ``None``."""
        start = self.clock.now_ms
        limit = start + round(timeout_s * 1000)
        while True:
            if predicate():
                return (self.clock.now_ms - start) / 1000.0
            if self.clock.now_ms >= limit:
                return None
            self.clock.advance_ms(min(step_ms, limit - self.clock.now_ms))

    # -- judgement ----------------------------------------------------------
    def expected_digest(self) -> dict[str, tuple[str, int]]:
        return {h.node_id: h.node.local_key() for h in self.running() if h.node}

    def converged(self) -> bool:
        expected = self.expected_digest()
        return all(h.node is not None and h.node.records() == expected
                   for h in self.running())

    def time_to_converge(self, timeout_s: float = 30.0) -> float | None:
        return self.run_until(self.converged, timeout_s)

    def assert_converged(self, within_ms: int) -> float:
        elapsed = self.time_to_converge(within_ms / 1000.0)
        if elapsed is None:
            raise BudgetExceeded(f"mesh did not converge within {within_ms} ms; "
                                 f"{self.describe_divergence()}")
        return elapsed

    def describe_divergence(self) -> str:
        expected = self.expected_digest()
        problems = []
        for handle in self.running():
            have = handle.node.records() if handle.node else {}
            missing = sorted(set(expected) - set(have))
            extra = sorted(set(have) - set(expected))
            stale = sorted(n for n in set(have) & set(expected) if have[n] != expected[n])
            if missing or extra or stale:
                problems.append(f"{handle.name}: missing={len(missing)} "
                                f"extra={len(extra)} stale={len(stale)}")
        return "; ".join(problems) or "no divergence"

    def check_invariants(self, *, loss_budget_s: float = 7.0) -> list[str]:
        """Safety properties that must hold once the network is healed and settled."""
        problems: list[str] = []
        running_ids = {h.node_id for h in self.running()}
        for handle in self.running():
            records = handle.node.records() if handle.node else {}
            if len(records) > mm.MAX_NODES:
                problems.append(f"{handle.name} holds {len(records)} nodes (> cap)")
            for node_id, (boot_id, _rev) in records.items():
                owner = next((h for h in self.nodes.values() if h.node_id == node_id), None)
                if owner is None:
                    problems.append(f"{handle.name} knows an unknown node")
                elif node_id not in running_ids:
                    problems.append(f"{handle.name} still lists dead node {owner.name}")
                elif owner.boot_id != boot_id:
                    problems.append(f"{handle.name} holds an old boot of {owner.name}")
        return problems

    # -- budget helpers -----------------------------------------------------
    def measure_join(self, name: str | None = None, timeout_s: float = 10.0) -> float:
        before = self.clock.now_ms
        self.add(name)
        elapsed = self.time_to_converge(timeout_s)
        if elapsed is None:
            raise BudgetExceeded(f"join did not converge in {timeout_s}s: "
                                 f"{self.describe_divergence()}")
        self.metrics["join_s"].append((self.clock.now_ms - before) / 1000.0)
        return elapsed

    def measure_leave(self, handle: NodeHandle, *, clean: bool, timeout_s: float = 15.0) -> float:
        self.stop(handle, clean=clean)
        elapsed = self.time_to_converge(timeout_s)
        if elapsed is None:
            raise BudgetExceeded(f"leave did not converge in {timeout_s}s: "
                                 f"{self.describe_divergence()}")
        self.metrics["leave_clean_s" if clean else "silent_loss_s"].append(elapsed)
        return elapsed

    def measure_target(self, handle: NodeHandle, target_id: str,
                       timeout_s: float = 10.0) -> float:
        self.add_target(handle, target_id)
        elapsed = self.run_until(
            lambda: all(target_id in h.node.target_ids() for h in self.running() if h.node),
            timeout_s)
        if elapsed is None:
            raise BudgetExceeded(f"target {target_id} not visible everywhere in {timeout_s}s")
        self.metrics["target_visible_s"].append(elapsed)
        return elapsed

    def egress_per_node(self, window_s: int = 10) -> float:
        """Mean bytes/s sent per running node over the last *window_s* seconds."""
        nodes = self.running()
        if not nodes:
            return 0.0
        return sum(self.net.egress_bytes_per_s(h.address, window_s) for h in nodes) / len(nodes)

    def assert_budget(self, name: str, value: float, *, limit: float | None = None) -> None:
        bound = BUDGETS[name] if limit is None else limit
        if value > bound:
            raise BudgetExceeded(f"{name}: measured {value:.3f} > budget {bound:.3f}")

    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seed": self.seed, "virtual_s": self.clock.now_ms / 1000.0,
                               "events": self.clock.events_run,
                               "nodes": len(self.running())}
        for name, values in sorted(self.metrics.items()):
            out[name] = {"n": len(values), "p50": percentile(values, 50),
                         "p99": percentile(values, 99), "max": max(values)}
        out["egress_bytes_per_s_per_node"] = round(self.egress_per_node(), 1)
        return out


# ---------------------------------------------------------------------------
# Seeded random scenarios


def random_scenario(world: SimWorld, *, steps: int = 12, nodes: int = 4,
                    allow_multicast_outage: bool = False) -> None:
    """Apply random churn, then heal everything and let the mesh settle."""
    rng = world.rng
    world.join(nodes)
    world.run(3)
    for _ in range(steps):
        live = world.running()
        action = rng.choice(["join", "leave", "crash", "sleep", "wake", "ip",
                             "partition", "heal", "target", "loss", "idle"]
                            + (["mcast"] if allow_multicast_outage else []))
        if action == "join" and len(world.nodes) < nodes + 4:
            world.add()
        elif action == "leave" and len(live) > 1:
            world.stop(rng.choice(live), clean=True)
        elif action == "crash" and len(live) > 1:
            world.crash(rng.choice(live))
        elif action == "sleep" and len(live) > 1:
            world.sleep(rng.choice(live))
        elif action == "wake":
            asleep = [h for h in world.nodes.values() if h.state == "asleep"]
            if asleep:
                world.wake(rng.choice(asleep))
        elif action == "ip" and live:
            world.change_ip(rng.choice(live))
        elif action == "partition" and len(live) > 2:
            shuffled = live[:]
            rng.shuffle(shuffled)
            cut = rng.randint(1, len(shuffled) - 1)
            world.partition(shuffled[:cut], shuffled[cut:])
        elif action == "heal":
            world.heal()
        elif action == "target" and live:
            world.add_target(rng.choice(live), f"tv-{rng.randint(0, 999):03d}")
        elif action == "loss":
            world.set_loss(rng.choice([0.0, 0.05, 0.2]))
        elif action == "mcast":
            world.set_multicast(rng.random() < 0.5)
        world.run(rng.uniform(0.2, 4.0))
    world.heal()
    world.set_loss(0.0)
    world.set_multicast(True)
    for handle in list(world.nodes.values()):
        if handle.state == "asleep":
            world.wake(handle)
    world.run(12)


def run_seeds(seeds: range | list[int], scenario: Callable[[SimWorld], None] = random_scenario,
              factory: NodeFactory | None = None, **node_kwargs: Any) -> list[dict[str, Any]]:
    """Run *scenario* once per seed; return failure descriptions (empty = all passed)."""
    failures = []
    for seed in seeds:
        world = SimWorld(seed, factory, **node_kwargs)
        world.net.log_enabled = False
        scenario(world)
        problems = []
        if not world.converged():
            problems.append("not converged: " + world.describe_divergence())
        problems += world.check_invariants()
        if problems:
            failures.append({"seed": seed, "problems": problems})
    return failures
