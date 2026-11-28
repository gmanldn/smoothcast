"""Fast presence beacon for the SmoothCast mesh (ticket #396, "M3").

Small UDP messages let full nodes find each other in well under a second and
notice a clean exit immediately. The beacon is a **hint layer**: it carries only
public-tier identity (no names of targets, clients or media) and never removes
or authenticates anything by itself. It reports what it hears as events;
membership (#397) decides who is alive and replication (#398) fetches records.

Behaviour
---------
* ``HELLO`` bursts at 0/100/300/700/1500 ms (with jitter) on start, wake from
  sleep and address change; peers answer with a unicast ``WELCOME``.
* ``HEARTBEAT`` about once a second (+/-20 % jitter), also sent right away when the
  local record revision changes so peers learn of it in one round trip.
* ``GOODBYE`` (sent twice) on a clean close.
* Seeds: when multicast yields nothing, configured seed addresses and addresses
  gossiped in ``WELCOME`` are contacted by unicast, and peers not heard over
  multicast get unicast heartbeats, so a multicast-hostile network still works.
* Loop and abuse protection: own beacons ignored, datagrams limited to 512 bytes,
  per-source token buckets, bounded peer table (the newest unknown node is
  refused, never an established one), non-LAN sources ignored.

Written only against ``mesh_ports`` so the simulator (tests/mesh_sim.py) and real
sockets (``mesh_udp``) run the same code. GTK-free.
Design: docs/MESH_DESIGN.md ("Fast presence").
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
import random
import re

import mesh_model
from mesh_ports import Clock, Datagram, TimerHandle, Transport

PROTOCOL_VERSION = 1
MAX_DATAGRAM = 512
MAX_PEERS = mesh_model.MAX_NODES
MAX_HINTS = 6
HEARTBEAT_S = 1.0
BURST_OFFSETS_S = (0.0, 0.1, 0.3, 0.7, 1.5)
SEED_DELAY_S = 2.0
SEED_RETRY_S = 5.0
UNICAST_AFTER_S = 2.5            # no multicast from a peer for this long -> unicast beats
PEER_FORGET_S = 300.0
RIVAL_WINDOW_S = 5.0
NONCE_TTL_S = 10.0
ADDRESS_CLAIM_S = 1.6      # a live address cannot be displaced by another source
RATE_CAPACITY = 24.0
RATE_REFILL_PER_S = 12.0
MAX_BUCKETS = 256
DEFAULT_PORT = 47602

_HEX32 = re.compile(r"^[a-f0-9]{32}$")
_NONCE = re.compile(r"^[a-f0-9]{16}$")
_KINDS = {"H": "hello", "W": "welcome", "B": "heartbeat", "G": "goodbye"}
_KIND_CODES = {name: code for code, name in _KINDS.items()}


class BeaconError(ValueError):
    """A datagram is malformed or oversized."""


# ---------------------------------------------------------------------------
# Wire format


@dataclass(frozen=True)
class Message:
    kind: str                  # hello | welcome | heartbeat | goodbye
    node_id: str
    boot_id: str
    incarnation: int
    rev: int
    boot_epoch: int
    port: int                  # the node's mesh (sync) port
    nonce: str
    echo: str = ""             # WELCOME: the HELLO nonce being answered
    hints: tuple[tuple[str, int], ...] = ()


def encode(message: Message) -> bytes:
    body = {
        "k": _KIND_CODES[message.kind], "v": PROTOCOL_VERSION,
        "n": message.node_id, "b": message.boot_id,
        "i": message.incarnation, "r": message.rev,
        "e": message.boot_epoch, "p": message.port, "x": message.nonce,
    }
    if message.echo:
        body["y"] = message.echo
    if message.hints:
        body["h"] = [[ip, port] for ip, port in message.hints[:MAX_HINTS]]
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(data) > MAX_DATAGRAM:
        raise BeaconError("beacon exceeds the datagram limit")
    return data


def _int(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise BeaconError("integer field out of range")
    return value


def decode(data: bytes) -> Message:
    """Parse an untrusted datagram. Raises only :class:`BeaconError`."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_DATAGRAM:
        raise BeaconError("datagram is too large")
    try:
        raw = json.loads(bytes(data).decode("ascii"),
                         parse_constant=lambda _name: (_ for _ in ()).throw(
                             BeaconError("bad constant")))
    except BeaconError:
        raise
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise BeaconError("datagram is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise BeaconError("datagram must be an object")
    code = raw.get("k")
    kind = _KINDS.get(code) if isinstance(code, str) else None
    if kind is None:
        raise BeaconError("unknown message kind")
    if raw.get("v") != PROTOCOL_VERSION or type(raw.get("v")) is not int:
        raise BeaconError("unsupported protocol version")
    for key, pattern in (("n", _HEX32), ("b", _HEX32), ("x", _NONCE)):
        if not isinstance(raw.get(key), str) or not pattern.fullmatch(raw[key]):
            raise BeaconError(f"field {key} is invalid")
    echo = raw.get("y", "")
    if echo != "" and (not isinstance(echo, str) or not _NONCE.fullmatch(echo)):
        raise BeaconError("echo is invalid")
    hints: list[tuple[str, int]] = []
    raw_hints = raw.get("h", [])
    if not isinstance(raw_hints, list) or len(raw_hints) > MAX_HINTS:
        raise BeaconError("hints are invalid")
    for item in raw_hints:
        if (not isinstance(item, list) or len(item) != 2
                or not mesh_model.is_lan_address(item[0])):
            raise BeaconError("hint is invalid")
        hints.append((item[0], _int(item[1], 1, 65535)))
    return Message(
        kind=kind, node_id=raw["n"], boot_id=raw["b"],
        incarnation=_int(raw.get("i"), 0, mesh_model._MAX_COUNTER),
        rev=_int(raw.get("r"), 0, mesh_model._MAX_COUNTER),
        boot_epoch=_int(raw.get("e"), 0, mesh_model._MAX_EPOCH),
        port=_int(raw.get("p"), 1, 65535), nonce=raw["x"], echo=echo,
        hints=tuple(hints))


# ---------------------------------------------------------------------------
# Events and local state


@dataclass
class LocalState:
    """What this node announces. Mutate through :meth:`Beacon.update_local`."""

    node_id: str
    boot_id: str
    boot_epoch: int
    port: int
    incarnation: int = 0
    rev: int = 0


@dataclass(frozen=True)
class PeerSeen:
    """First sight of a node, a restart (new boot) or a move to a new address."""

    node_id: str
    boot_id: str
    address: str
    port: int
    incarnation: int
    rev: int
    boot_epoch: int
    why: str                   # "new" | "restart" | "moved"


@dataclass(frozen=True)
class PeerBeat:
    """A heartbeat/hello/welcome from a node's *current* boot."""

    node_id: str
    boot_id: str
    address: str
    incarnation: int
    rev: int
    multicast: bool
    port: int = 0
    boot_epoch: int = 0


@dataclass(frozen=True)
class PeerGone:
    """A goodbye from the node's current boot, from its known address (a hint)."""

    node_id: str
    boot_id: str
    address: str
    reason: str = "goodbye"


@dataclass(frozen=True)
class RevAhead:
    """A peer announced a newer record revision than we have seen: pull it."""

    node_id: str
    boot_id: str
    address: str
    port: int
    rev: int


@dataclass(frozen=True)
class DuplicateIdentity:
    """Two live processes claim one ``node_id`` (cloned configuration)."""

    node_id: str
    boot_id: str
    address: str
    own: bool                  # True when the clash is with this very node
    boot_epoch: int = 0        # the other process's announced start time


BeaconEvent = PeerSeen | PeerBeat | PeerGone | RevAhead | DuplicateIdentity


@dataclass
class _Peer:
    node_id: str
    boot_id: str
    boot_epoch: int
    incarnation: int
    rev: int
    address: str
    port: int
    last_heard: float
    last_multicast: float = -1e9
    rival_seen: float = -1e9
    addr_heard: float = -1e9      # last beat from the *current* address


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class BeaconStats:
    received: int = 0
    malformed: int = 0
    rate_limited: int = 0
    ignored_own: int = 0
    ignored_source: int = 0
    refused_full: int = 0
    spoofed_goodbyes: int = 0
    stale_boots: int = 0
    sent: int = 0
    callback_errors: int = 0
    address_conflicts: int = 0
    unsolicited_welcomes: int = 0


@dataclass
class BeaconConfig:
    heartbeat_s: float = HEARTBEAT_S
    burst_offsets_s: tuple[float, ...] = BURST_OFFSETS_S
    seed_delay_s: float = SEED_DELAY_S
    seed_retry_s: float = SEED_RETRY_S
    jitter: float = 0.2
    seeds: tuple[str, ...] = ()           # "ip" or "ip:port"
    welcome_jitter_s: float = 0.05


class Beacon:
    """Presence beacon for one node on one interface."""

    def __init__(self, *, clock: Clock, transport: Transport, rng: random.Random,
                 local: LocalState, on_event: Callable[[BeaconEvent], None],
                 config: BeaconConfig | None = None) -> None:
        self._clock = clock
        self._transport = transport
        self._rng = rng
        self.local = local
        self._emit = on_event
        self.config = config or BeaconConfig()
        self.stats = BeaconStats()
        self._peers: dict[str, _Peer] = {}
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._timers: list[TimerHandle] = []
        self._burst_timers: list[TimerHandle] = []
        self._welcomed: dict[str, float] = {}
        self._contacted: dict[str, float] = {}
        self._dup_reported: dict[str, float] = {}
        self._local_dirty: TimerHandle | None = None
        self._started = False
        self._closed = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._started or self._closed:
            return
        self._started = True
        self._transport.set_datagram_handler(self._on_datagram)
        self._burst()
        self._schedule(self._jittered(self.config.heartbeat_s), self._heartbeat_tick)
        self._schedule(self.config.seed_delay_s, self._seed_tick)
        self._schedule(10.0, self._housekeeping)

    def close(self, *, graceful: bool = True) -> None:
        """Stop everything. Idempotent; sends GOODBYE twice when *graceful*."""
        if self._closed:
            return
        self._closed = True
        if graceful and self._started:
            for _ in range(2):
                self._send_multicast("goodbye")
            for peer in self._unicast_peers():
                self._send_unicast(peer.address, "goodbye")
        for timer in self._timers + self._burst_timers:
            timer.cancel()
        if self._local_dirty is not None:
            self._local_dirty.cancel()
        self._timers.clear()
        self._burst_timers.clear()
        self._transport.set_datagram_handler(None)
        self._transport.close()

    # -- local changes ------------------------------------------------------
    def update_local(self, *, rev: int | None = None,
                     incarnation: int | None = None) -> None:
        """Record a new local revision/incarnation and announce it promptly."""
        if rev is not None:
            self.local.rev = rev
        if incarnation is not None:
            self.local.incarnation = incarnation
        if self._started and not self._closed and self._local_dirty is None:
            self._local_dirty = self._clock.call_later(0.02, self._flush_local)

    def _flush_local(self) -> None:
        self._local_dirty = None
        if not self._closed:
            self._send_heartbeat()

    def notify_wake(self) -> None:
        """The machine resumed from sleep: re-announce and re-seed immediately."""
        if self._started and not self._closed:
            self.local.incarnation += 1
            self._burst()
            self._contact_seeds(force=True)

    def notify_address_changed(self) -> None:
        """The interface address changed: peers must learn the new source."""
        if self._started and not self._closed:
            self._burst()
            self._contact_seeds(force=True)

    def contact(self, address: str) -> None:
        """Hint from another discovery source (mDNS, user entry): say hello."""
        if self._closed or not self._started:
            return
        now = self._clock.monotonic()
        if now - self._contacted.get(address, -1e9) < 10.0 or len(self._contacted) > 512:
            return
        self._contacted[address] = now
        self._send_unicast(address, "hello")

    def forget(self, node_id: str) -> None:
        """Drop a peer (membership declared it dead) so a return is seen as new."""
        self._peers.pop(node_id, None)

    # -- inspection ---------------------------------------------------------
    def peers(self) -> list[_Peer]:
        return sorted(self._peers.values(), key=lambda p: p.node_id)

    def peer(self, node_id: str) -> _Peer | None:
        return self._peers.get(node_id)

    # -- timers -------------------------------------------------------------
    def _jittered(self, base: float) -> float:
        spread = self.config.jitter
        return base * (1.0 - spread + 2.0 * spread * self._rng.random())

    def _schedule(self, delay: float, callback: Callable[[], None]) -> None:
        self._timers.append(self._clock.call_later(delay, callback))
        if len(self._timers) > 64:                       # drop handles that fired
            self._timers = self._timers[-32:]

    def _burst(self) -> None:
        for timer in self._burst_timers:
            timer.cancel()
        self._burst_timers = [
            self._clock.call_later(self._jittered(offset) if offset else 0.0,
                                   lambda: self._send_multicast("hello"))
            for offset in self.config.burst_offsets_s]

    def _heartbeat_tick(self) -> None:
        if self._closed:
            return
        self._send_heartbeat()
        self._schedule(self._jittered(self.config.heartbeat_s), self._heartbeat_tick)

    def _send_heartbeat(self) -> None:
        self._send_multicast("heartbeat")
        for peer in self._unicast_peers():
            self._send_unicast(peer.address, "heartbeat", hints=True)

    def _unicast_peers(self) -> list[_Peer]:
        """Peers we have not heard over multicast recently (blocked or seeded)."""
        now = self._clock.monotonic()
        return [p for p in self._peers.values()
                if now - p.last_multicast > UNICAST_AFTER_S
                and now - p.last_heard <= PEER_FORGET_S]

    def _seed_tick(self) -> None:
        if self._closed:
            return
        self._contact_seeds(force=False)
        self._schedule(self.config.seed_retry_s, self._seed_tick)

    def _contact_seeds(self, *, force: bool) -> None:
        """Unicast HELLO to seeds we have not heard from (or to all when forced)."""
        known = {p.address for p in self._peers.values()}
        for seed in self.config.seeds:
            if force or seed.rsplit(":", 1)[0] not in known:
                self._send_unicast(seed, "hello")

    def _housekeeping(self) -> None:
        if self._closed:
            return
        now = self._clock.monotonic()
        for node_id, peer in list(self._peers.items()):
            if now - peer.last_heard > PEER_FORGET_S:
                del self._peers[node_id]
        for table in (self._welcomed, self._contacted, self._dup_reported):
            for key, stamp in list(table.items()):
                if now - stamp > 60.0:
                    del table[key]
        self._schedule(10.0, self._housekeeping)

    # -- sending ------------------------------------------------------------
    def _message(self, kind: str, *, echo: str = "", hints: bool = False) -> bytes:
        nonce = "%016x" % self._rng.getrandbits(64)
        if kind == "hello":
            self._nonces[nonce] = self._clock.monotonic()
            while len(self._nonces) > 64:
                self._nonces.popitem(last=False)
        gossip: tuple[tuple[str, int], ...] = ()
        if hints:
            gossip = tuple((p.address, p.port) for p in self.peers()[:MAX_HINTS])
        return encode(Message(
            kind=kind, node_id=self.local.node_id, boot_id=self.local.boot_id,
            incarnation=self.local.incarnation, rev=self.local.rev,
            boot_epoch=self.local.boot_epoch, port=self.local.port,
            nonce=nonce, echo=echo, hints=gossip))

    def _send_multicast(self, kind: str) -> None:
        self.stats.sent += 1
        self._transport.send_multicast(self._message(kind))

    def _send_unicast(self, address: str, kind: str, *, echo: str = "",
                      hints: bool = False) -> None:
        self.stats.sent += 1
        self._transport.send_unicast(address, self._message(kind, echo=echo, hints=hints))

    # -- receiving ----------------------------------------------------------
    def _allow(self, source: str) -> bool:
        now = self._clock.monotonic()
        bucket = self._buckets.get(source)
        if bucket is None:
            bucket = self._buckets[source] = _Bucket(RATE_CAPACITY, now)
            while len(self._buckets) > MAX_BUCKETS:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(source)
        bucket.tokens = min(RATE_CAPACITY,
                            bucket.tokens + (now - bucket.updated) * RATE_REFILL_PER_S)
        bucket.updated = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True

    def _on_datagram(self, datagram: Datagram) -> None:
        if self._closed:
            return
        self.stats.received += 1
        if not mesh_model.is_lan_address(datagram.src):
            self.stats.ignored_source += 1
            return
        if not self._allow(datagram.src):
            self.stats.rate_limited += 1
            return
        try:
            message = decode(datagram.payload)
        except BeaconError:
            self.stats.malformed += 1
            return
        try:
            self._handle(message, datagram)
        except Exception:                      # a bad handler must never kill the loop  # noqa: BLE001 - a bad handler must never kill the loop; counted
            self.stats.callback_errors += 1

    def _emit_safe(self, event: BeaconEvent) -> None:
        try:
            self._emit(event)
        except Exception:  # noqa: BLE001 - a bad callback must never kill the loop; counted
            self.stats.callback_errors += 1

    def _handle(self, message: Message, datagram: Datagram) -> None:
        now = self._clock.monotonic()
        if message.node_id == self.local.node_id:
            if message.boot_id == self.local.boot_id:
                self.stats.ignored_own += 1          # our own multicast echo
                return
            if now - self._dup_reported.get(message.boot_id, -1e9) > 30.0:
                self._dup_reported[message.boot_id] = now
                self._emit_safe(DuplicateIdentity(message.node_id, message.boot_id,
                                                  datagram.src, True, message.boot_epoch))
            return
        if message.kind == "welcome":
            sent = self._nonces.get(message.echo)
            if sent is None or now - sent > NONCE_TTL_S:
                self.stats.unsolicited_welcomes += 1   # replayed or forged reply
                return
        if message.kind == "goodbye":
            self._handle_goodbye(message, datagram)
            return
        self._observe(message, datagram, now)
        if message.kind == "hello":
            self._schedule_welcome(message, datagram.src, now)
        for ip, _port in message.hints:
            # The hint's port is the peer's mesh (sync) port; presence always
            # talks to the fixed beacon port, so only the address matters here.
            if (not any(p.address == ip for p in self._peers.values())
                    and ip != self._transport.address):
                self.contact(ip)

    def _schedule_welcome(self, message: Message, source: str, now: float) -> None:
        if now - self._welcomed.get(source, -1e9) < 0.5:
            return
        self._welcomed[source] = now
        delay = self._rng.random() * self.config.welcome_jitter_s
        echo = message.nonce

        def reply() -> None:
            if not self._closed:
                self._send_unicast(source, "welcome", echo=echo, hints=True)
        self._clock.call_later(delay, reply)

    def _handle_goodbye(self, message: Message, datagram: Datagram) -> None:
        peer = self._peers.get(message.node_id)
        if peer is None or peer.boot_id != message.boot_id or peer.address != datagram.src:
            self.stats.spoofed_goodbyes += 1         # unknown, stale or forged
            return
        del self._peers[message.node_id]
        self._emit_safe(PeerGone(message.node_id, message.boot_id, datagram.src))

    def _observe(self, message: Message, datagram: Datagram, now: float) -> None:
        peer = self._peers.get(message.node_id)
        src = datagram.src
        if peer is None:
            if len(self._peers) >= MAX_PEERS:
                self.stats.refused_full += 1         # refuse the newest, keep the mesh
                return
            peer = self._peers[message.node_id] = _Peer(
                message.node_id, message.boot_id, message.boot_epoch,
                message.incarnation, message.rev, src, message.port, now)
            peer.addr_heard = now
            if datagram.multicast:
                peer.last_multicast = now
            self._emit_safe(PeerSeen(message.node_id, message.boot_id, src, message.port,
                                     message.incarnation, message.rev,
                                     message.boot_epoch, "new"))
            self._emit_safe(PeerBeat(message.node_id, message.boot_id, src,
                                     message.incarnation, message.rev, datagram.multicast,
                                     message.port, message.boot_epoch))
            return
        if peer.boot_id != message.boot_id:
            if message.boot_epoch < peer.boot_epoch:
                # An older boot is still talking. Either a delayed datagram from
                # before a restart (harmless) or a clone: report a clash only when
                # the current boot is also actively heard.
                self.stats.stale_boots += 1
                if (now - peer.last_heard < RIVAL_WINDOW_S
                        and now - self._dup_reported.get(message.node_id, -1e9) > 30.0):
                    self._dup_reported[message.node_id] = now
                    self._emit_safe(DuplicateIdentity(message.node_id, message.boot_id,
                                                      src, False, message.boot_epoch))
                return
            peer.boot_id, peer.boot_epoch = message.boot_id, message.boot_epoch
            peer.incarnation, peer.rev = message.incarnation, message.rev
            peer.address, peer.port = src, message.port
            peer.last_heard = peer.addr_heard = now
            if datagram.multicast:
                peer.last_multicast = now
            self._emit_safe(PeerSeen(message.node_id, message.boot_id, src, message.port,
                                     message.incarnation, message.rev,
                                     message.boot_epoch, "restart"))
            self._emit_safe(PeerBeat(message.node_id, message.boot_id, src,
                                     message.incarnation, message.rev, datagram.multicast,
                                     message.port, message.boot_epoch))
            return
        if peer.address != src:
            if now - peer.addr_heard < ADDRESS_CLAIM_S:
                # The node is still beating from its known address: a second source
                # using its identity is a conflict (or a spoof), never a move.
                self.stats.address_conflicts += 1
                return
        else:
            peer.addr_heard = now
        moved = peer.address != src or peer.port != message.port
        peer.last_heard = now
        if datagram.multicast:
            peer.last_multicast = now
        peer.incarnation = max(peer.incarnation, message.incarnation)
        if moved:
            peer.address, peer.port = src, message.port
            peer.addr_heard = now
            self._emit_safe(PeerSeen(message.node_id, message.boot_id, src, message.port,
                                     peer.incarnation, message.rev, message.boot_epoch,
                                     "moved"))
        ahead = message.rev > peer.rev
        if ahead:
            peer.rev = message.rev
        self._emit_safe(PeerBeat(message.node_id, message.boot_id, src, message.incarnation,
                                 message.rev, datagram.multicast, message.port,
                                 message.boot_epoch))
        if ahead:
            self._emit_safe(RevAhead(message.node_id, message.boot_id, src,
                                     message.port, message.rev))


def parse_seeds(values: Iterable[object]) -> tuple[str, ...]:
    """Validate user-entered seed addresses (``ip`` or ``ip:port``); drop the rest."""
    seeds: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        host, _, port = value.strip().partition(":")
        if not mesh_model.is_lan_address(host):
            continue
        if port and not (port.isdigit() and 1 <= int(port) <= 65535):
            continue
        seeds.append(host if not port else f"{host}:{int(port)}")
    return tuple(dict.fromkeys(seeds))[:16]


__all__ = [
    "Beacon", "BeaconConfig", "BeaconError", "BeaconEvent", "BeaconStats",
    "DuplicateIdentity", "LocalState", "Message", "PeerBeat", "PeerGone", "PeerSeen",
    "RevAhead", "decode", "encode", "parse_seeds",
]
