"""Membership and failure detection for the SmoothCast mesh (ticket #397, "M4").

Decides which nodes are alive, quickly and *correctly*. It consumes presence
events from the beacon (#396), probes silent peers over the RPC channel, and
reports ``NodeUp``/``NodeSuspect``/``NodeDown``/``NodeRefuted``/``NodeMoved``/
``IdentityClash`` events for replication (#398), roles (#399) and the UI.

SWIM-style, tuned for a home LAN of at most a few dozen nodes:

* ``alive`` -> after ``suspect_after`` seconds without a beat, probe the peer
  directly. An ack keeps it alive; a failed probe makes it ``suspect`` and asks up
  to three other nodes to probe it indirectly (one flaky link never condemns a
  healthy node). ``suspect`` -> ``dead`` after ``suspect_timeout`` more seconds.
* A node refutes suspicion by raising its *incarnation*; any first-hand beat or
  ack also clears it.
* ``dead`` nodes are kept as tombstones (60 s, bounded). Only first-hand evidence
  from the node itself revives a timed-out node (partition heal); a goodbye'd
  boot never revives; second-hand claims need a higher incarnation or a new boot.
* A goodbye is a *hint*: it is confirmed by a direct probe before removal.
* Only monotonic receive times are used. A long local pause (sleep) or wall-clock
  jump grants every peer a grace period and triggers a re-announcement instead of
  mass suspicion.

Written against ``mesh_ports`` and ``mesh_rpc`` only (GTK-free). Design:
docs/MESH_DESIGN.md ("Membership and failure detection").
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
import random
from typing import Any

import mesh_beacon as mb
import mesh_model
from mesh_ports import Clock, TimerHandle
from mesh_rpc import RpcRouter

ALIVE, SUSPECT, DEAD = "alive", "suspect", "dead"
MAX_TOMBSTONES = mesh_model.MAX_NODES


@dataclass
class MembershipConfig:
    tick_s: float = 0.25
    suspect_after_s: float = 3.0       # three missed one-second heartbeats
    probe_timeout_s: float = 1.0
    suspect_timeout_s: float = 2.5
    indirect_probes: int = 3
    tombstone_s: float = 60.0
    goodbye_confirm_s: float = 0.35
    wake_gap_s: float = 2.0
    wall_drift_s: float = 5.0
    wake_grace_s: float = 4.0
    witness_recency_s: float = 1.5     # a helper vouches only for peers it heard this recently


# -- events -------------------------------------------------------------------


@dataclass(frozen=True)
class NodeUp:
    node_id: str
    boot_id: str
    address: str
    port: int
    why: str                    # "new" | "restart" | "revived"


@dataclass(frozen=True)
class NodeSuspect:
    node_id: str
    boot_id: str


@dataclass(frozen=True)
class NodeDown:
    node_id: str
    boot_id: str
    reason: str                 # "timeout" | "goodbye"


@dataclass(frozen=True)
class NodeRefuted:
    node_id: str
    boot_id: str
    incarnation: int


@dataclass(frozen=True)
class NodeMoved:
    node_id: str
    boot_id: str
    address: str
    port: int


@dataclass(frozen=True)
class IdentityClash:
    """Two processes claim one node id. ``regenerate`` tells *us* to pick a new id."""

    node_id: str
    other_boot_id: str
    own: bool
    regenerate: bool


MembershipEvent = NodeUp | NodeSuspect | NodeDown | NodeRefuted | NodeMoved | IdentityClash


@dataclass
class Member:
    node_id: str
    boot_id: str
    boot_epoch: int
    incarnation: int
    rev: int
    address: str
    port: int
    last_heard: float
    status: str = ALIVE
    suspect_since: float = 0.0
    probing: bool = False
    probe_token: int = 0
    probe_started: float = 0.0


@dataclass
class Tombstone:
    node_id: str
    boot_id: str
    incarnation: int
    reason: str
    since: float


@dataclass
class MembershipStats:
    probes: int = 0
    probe_failures: int = 0
    suspicions: int = 0
    refutations: int = 0
    downs: int = 0
    false_positives: int = 0          # declared dead, later revived first-hand
    indirect_saves: int = 0
    goodbyes_confirmed: int = 0
    goodbyes_refuted: int = 0
    wakes: int = 0


def later_started_regenerates(own_epoch: int, own_boot: str,
                              other_epoch: int, other_boot: str) -> bool:
    """Deterministic tie-break: the process that started later gives up the id."""
    return (own_epoch, own_boot) > (other_epoch, other_boot)


class Membership:
    def __init__(self, *, clock: Clock, rpc: RpcRouter, rng: random.Random,
                 beacon: mb.Beacon, on_event: Callable[[MembershipEvent], None],
                 config: MembershipConfig | None = None,
                 on_regenerate: Callable[[], None] | None = None) -> None:
        self._clock = clock
        self._rpc = rpc
        self._rng = rng
        self._beacon = beacon
        self._emit = on_event
        self._regenerate = on_regenerate
        self.config = config or MembershipConfig()
        self.stats = MembershipStats()
        self._blocked: dict[str, str] = {}      # node_id -> last known address
        self._members: dict[str, Member] = {}
        self._tombstones: OrderedDict[str, Tombstone] = OrderedDict()
        self._timer: TimerHandle | None = None
        self._closed = False
        self._started = False
        self._last_tick = 0.0
        self._drift_base = 0.0
        self._probe_serial = 0
        rpc.register("ping", self._on_ping)
        rpc.register("pingreq", self._on_pingreq)

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._started or self._closed:
            return
        self._started = True
        self._last_tick = self._clock.monotonic()
        self._drift_base = self._clock.wall() - self._last_tick
        self._timer = self._clock.call_later(self.config.tick_s, self._tick)

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # -- inspection ---------------------------------------------------------
    def members(self, *, include_dead: bool = False) -> list[Member]:
        return sorted((m for m in self._members.values()
                       if include_dead or m.status != DEAD), key=lambda m: m.node_id)

    def member(self, node_id: str) -> Member | None:
        return self._members.get(node_id)

    def tombstone(self, node_id: str) -> Tombstone | None:
        return self._tombstones.get(node_id)

    # -- events from the beacon -------------------------------------------------
    # -- revocation ---------------------------------------------------------
    def block(self, node_id: str) -> None:
        """Revoke a peer: forget it and ignore it until :meth:`unblock`."""
        member = self._members.get(node_id)
        self._blocked[node_id] = member.address if member is not None else ""
        while len(self._blocked) > 2 * mesh_model.MAX_NODES:
            self._blocked.pop(next(iter(self._blocked)))
        if member is not None:
            self._bury(member, "revoked")

    def unblock(self, node_id: str) -> None:
        if self._blocked.pop(node_id, None) is not None:
            self._beacon.forget(node_id)      # its next beat is seen as a fresh arrival

    def is_blocked_address(self, address: str) -> bool:
        return address in self._blocked.values()

    def on_beacon_event(self, event: mb.BeaconEvent) -> None:
        if self._closed:
            return
        if getattr(event, "node_id", None) in self._blocked:
            return
        if isinstance(event, mb.PeerSeen):
            self._on_seen(event)
        elif isinstance(event, mb.PeerBeat):
            self._on_beat(event)
        elif isinstance(event, mb.PeerGone):
            self._on_goodbye(event)
        elif isinstance(event, mb.DuplicateIdentity):
            self._on_clash(event)

    def _emit_safe(self, event: MembershipEvent) -> None:
        try:
            self._emit(event)
        except Exception:
            pass

    def _bury(self, member: Member, reason: str) -> None:
        now = self._clock.monotonic()
        member.status = DEAD
        self._tombstones[member.node_id] = Tombstone(
            member.node_id, member.boot_id, member.incarnation, reason, now)
        self._tombstones.move_to_end(member.node_id)
        while len(self._tombstones) > MAX_TOMBSTONES:
            self._tombstones.popitem(last=False)
        del self._members[member.node_id]
        self.stats.downs += 1
        if reason in {"timeout", "revoked"}:
            self._beacon.forget(member.node_id)
        self._emit_safe(NodeDown(member.node_id, member.boot_id, reason))

    def _on_seen(self, event: mb.PeerSeen) -> None:
        now = self._clock.monotonic()
        member = self._members.get(event.node_id)
        if event.why == "moved" and member is not None and member.boot_id == event.boot_id:
            member.address, member.port = event.address, event.port
            self._emit_safe(NodeMoved(event.node_id, event.boot_id, event.address, event.port))
            return
        tomb = self._tombstones.get(event.node_id)
        if member is None:
            why = "restart" if (tomb is not None or event.why == "restart") else "new"
            if tomb is not None and tomb.boot_id == event.boot_id:
                if tomb.reason == "goodbye":
                    return                      # a late datagram from a departed boot
                self.stats.false_positives += 1
                why = "revived"
            self._tombstones.pop(event.node_id, None)
            if len(self._members) >= mesh_model.MAX_NODES:
                return                          # refuse the newest; keep the mesh
            self._members[event.node_id] = Member(
                event.node_id, event.boot_id, event.boot_epoch, event.incarnation,
                event.rev, event.address, event.port, now)
            self._emit_safe(NodeUp(event.node_id, event.boot_id, event.address,
                                   event.port, why))
            return
        if member.boot_id != event.boot_id:        # restart: the old boot is gone
            member.boot_id, member.boot_epoch = event.boot_id, event.boot_epoch
            member.incarnation, member.rev = event.incarnation, event.rev
            member.address, member.port = event.address, event.port
            member.last_heard, member.status, member.probing = now, ALIVE, False
            self._emit_safe(NodeUp(event.node_id, event.boot_id, event.address,
                                   event.port, "restart"))

    def _on_beat(self, beat: mb.PeerBeat) -> None:
        member = self._members.get(beat.node_id)
        if member is None:
            # A beat for a node we do not track (tombstone expired or beacon-first):
            # the beacon will have emitted PeerSeen; ignore stragglers.
            return
        if member.boot_id != beat.boot_id:
            return
        now = self._clock.monotonic()
        member.last_heard = now
        member.rev = max(member.rev, beat.rev)
        if beat.port:
            member.port = beat.port
        higher = beat.incarnation > member.incarnation
        if higher:
            member.incarnation = beat.incarnation
        if member.status == SUSPECT:
            self._clear_suspicion(member, refuted=higher)

    def _clear_suspicion(self, member: Member, *, refuted: bool) -> None:
        member.status = ALIVE
        member.probing = False
        if refuted:
            self.stats.refutations += 1
            self._emit_safe(NodeRefuted(member.node_id, member.boot_id, member.incarnation))

    def _on_goodbye(self, event: mb.PeerGone) -> None:
        member = self._members.get(event.node_id)
        if member is None or member.boot_id != event.boot_id:
            return
        token = self._next_token(member)
        member.probing = True

        def verdict(alive: bool) -> None:
            current = self._members.get(event.node_id)
            if current is None or current.probe_token != token:
                return
            current.probing = False
            if alive:
                self.stats.goodbyes_refuted += 1      # a forged goodbye
                current.last_heard = self._clock.monotonic()
                return
            self.stats.goodbyes_confirmed += 1
            self._bury(current, "goodbye")

        self._probe(member, verdict, timeout=self.config.goodbye_confirm_s)

    def _on_clash(self, event: mb.DuplicateIdentity) -> None:
        local = self._beacon.local
        if event.own:
            regenerate = later_started_regenerates(
                local.boot_epoch, local.boot_id, event.boot_epoch, event.boot_id)
            self._emit_safe(IdentityClash(event.node_id, event.boot_id, True, regenerate))
            if regenerate and self._regenerate is not None:
                try:
                    self._regenerate()
                except Exception:
                    pass
        else:
            self._emit_safe(IdentityClash(event.node_id, event.boot_id, False, False))

    # -- probing -----------------------------------------------------------------
    def _next_token(self, member: Member) -> int:
        self._probe_serial += 1
        member.probe_token = self._probe_serial
        return self._probe_serial

    def _probe(self, member: Member, done: Callable[[bool], None], *, timeout: float,
               suspect_incarnation: int | None = None) -> None:
        """Direct probe: ``done(True)`` on an ack from the expected boot."""
        self.stats.probes += 1
        node_id, boot_id = member.node_id, member.boot_id
        body: dict[str, Any] = {"from": self._beacon.local.node_id}
        if suspect_incarnation is not None:
            body["suspect"] = suspect_incarnation

        def reply(value: dict[str, Any] | None, error: str | None) -> None:
            if self._closed:
                return
            ok = (value is not None and value.get("node_id") == node_id
                  and value.get("boot_id") == boot_id)
            if ok and value is not None:
                inc = value.get("incarnation")
                current = self._members.get(node_id)
                if (current is not None and type(inc) is int and inc > current.incarnation):
                    current.incarnation = inc
                    self._emit_safe(NodeRefuted(node_id, boot_id, inc))
                    self.stats.refutations += 1
            else:
                self.stats.probe_failures += 1
            done(bool(ok))

        self._rpc.call(member.address, "ping", body, reply, timeout)

    def _on_ping(self, _source: str, body: dict[str, Any]) -> dict[str, Any]:
        local = self._beacon.local
        suspect = body.get("suspect")
        if type(suspect) is int and suspect >= local.incarnation:
            # Someone suspects us: refute by raising our incarnation.
            self._beacon.update_local(incarnation=suspect + 1)
        return {"node_id": local.node_id, "boot_id": local.boot_id,
                "incarnation": local.incarnation}

    def _on_pingreq(self, _source: str, body: dict[str, Any]) -> dict[str, Any] | None:
        """Indirect probe on behalf of a peer; resolves the target by *our* table."""
        node_id = body.get("target")
        if not isinstance(node_id, str):
            return {"ok": False}
        member = self._members.get(node_id)
        if member is None:
            return {"ok": False}
        # The transport's request handler is synchronous, so a helper vouches from
        # first-hand evidence: "I heard this node's own beat a moment ago". A node
        # that crashed stopped beating seconds ago and is therefore not vouched for.
        recent = self._clock.monotonic() - member.last_heard
        return {"ok": member.status == ALIVE and recent <= self.config.witness_recency_s}

    def _tick(self) -> None:
        if self._closed:
            return
        cfg = self.config
        now = self._clock.monotonic()
        wall_drift = (self._clock.wall() - now) - self._drift_base
        if now - self._last_tick > cfg.wake_gap_s or abs(wall_drift) > cfg.wall_drift_s:
            self._on_local_pause(now)
        self._last_tick = now
        self._drift_base = self._clock.wall() - now
        for member in list(self._members.values()):
            if member.status == ALIVE and not member.probing:
                if now - member.last_heard > cfg.suspect_after_s:
                    self._begin_probe(member)
            elif member.status == SUSPECT:
                if now - member.suspect_since > cfg.suspect_timeout_s:
                    self._bury(member, "timeout")
        for node_id, tomb in list(self._tombstones.items()):
            if now - tomb.since > cfg.tombstone_s:
                del self._tombstones[node_id]
        self._timer = self._clock.call_later(cfg.tick_s, self._tick)

    def notify_wake(self) -> None:
        """The OS reported resume from sleep (optional; ticks also detect it)."""
        if not self._closed:
            self._on_local_pause(self._clock.monotonic())

    def _on_local_pause(self, now: float) -> None:
        """We slept (or the wall clock jumped): peers are not at fault."""
        self.stats.wakes += 1
        for member in self._members.values():
            member.last_heard = now + self.config.wake_grace_s - self.config.suspect_after_s
            if member.status == SUSPECT:
                member.status, member.probing = ALIVE, False
        self._beacon.notify_wake()

    def _begin_probe(self, member: Member) -> None:
        member.probing = True
        token = self._next_token(member)

        def direct(alive: bool) -> None:
            current = self._members.get(member.node_id)
            if current is None or current.probe_token != token:
                return
            if alive:
                current.probing = False
                current.last_heard = self._clock.monotonic()
                return
            self._suspect(current, token)

        self._probe(member, direct, timeout=self.config.probe_timeout_s)

    def _suspect(self, member: Member, token: int) -> None:
        if member.status != ALIVE:
            return
        member.status = SUSPECT
        member.suspect_since = self._clock.monotonic()
        member.probing = False
        self.stats.suspicions += 1
        self._emit_safe(NodeSuspect(member.node_id, member.boot_id))
        helpers = [m for m in self._members.values()
                   if m.node_id != member.node_id and m.status == ALIVE]
        self._rng.shuffle(helpers)
        suspect_inc = member.incarnation
        for helper in helpers[:self.config.indirect_probes]:
            self._indirect(helper, member, token)
        # Also tell the suspect directly (when reachable) that it is suspected.
        self._probe(member, lambda alive: self._indirect_verdict(member.node_id, token, alive),
                    timeout=self.config.probe_timeout_s, suspect_incarnation=suspect_inc)

    def _indirect(self, helper: Member, target: Member, token: int) -> None:
        node_id = target.node_id

        def reply(value: dict[str, Any] | None, _error: str | None) -> None:
            if value is not None and value.get("ok") is True:
                self._indirect_verdict(node_id, token, True, indirect=True)

        self._rpc.call(helper.address, "pingreq", {"target": node_id}, reply,
                       self.config.probe_timeout_s)

    def _indirect_verdict(self, node_id: str, token: int, alive: bool,
                          *, indirect: bool = False) -> None:
        member = self._members.get(node_id)
        if not alive or member is None or member.probe_token != token:
            return
        if member.status == SUSPECT:
            if indirect:
                self.stats.indirect_saves += 1
            member.last_heard = self._clock.monotonic()
            self._clear_suspicion(member, refuted=False)

    # -- second-hand claims (from replication, #398) ------------------------------
    def observe_gossip(self, node_id: str, boot_id: str, incarnation: int,
                       status: str) -> bool:
        """Apply a peer's claim about a third node. Returns True if it changed state.

        A tombstone is superseded only by a new boot or a strictly higher
        incarnation, so delayed gossip cannot resurrect a dead node.
        """
        tomb = self._tombstones.get(node_id)
        if tomb is not None and status == ALIVE:
            if boot_id == tomb.boot_id and incarnation <= tomb.incarnation:
                return False
        member = self._members.get(node_id)
        if member is not None and member.boot_id == boot_id and incarnation > member.incarnation:
            member.incarnation = incarnation
            if member.status == SUSPECT and status == ALIVE:
                self._clear_suspicion(member, refuted=True)
            return True
        return False


__all__ = [
    "ALIVE", "DEAD", "IdentityClash", "Member", "Membership", "MembershipConfig",
    "MembershipEvent", "MembershipStats", "NodeDown", "NodeMoved", "NodeRefuted",
    "NodeSuspect", "NodeUp", "SUSPECT", "Tombstone", "later_started_regenerates",
]
