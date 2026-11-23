"""Delta-state replication between full nodes (ticket #398, "M5").

Every node owns exactly one record and replicates everyone else's. Changes
travel three ways, so speed never depends on a single packet surviving:

1. **Push** - a local change is announced to every alive peer within 50-100 ms
   (bursts coalesced).
2. **Pull on hint** - a heartbeat that shows a newer revision (``RevAhead``) or a
   node that just came up triggers an immediate digest exchange.
3. **Repair** - every 5-10 s (jittered) one random peer is synced, which mends
   any loss, partition or restart.

A sync is push-pull: ``{hash, digest}`` out; the answer carries only records the
requester lacks (chunked to stay under the RPC size cap) plus the responder's
digest, after which the requester pushes back whatever the responder lacks. When
the digest hashes match, the exchange is a few dozen bytes.

Per-peer back-pressure: one request in flight per peer, exponential backoff with
jitter, so a slow or dead peer never delays the others. Everything runs on the
mesh loop; nothing touches GTK. Trust note: relayed records are accepted only for
a node's current boot and only for nodes membership has seen alive; who may send
what to whom is the security tier's job (#404). Section-level deltas for very
large records are not implemented: records are capped at 16 KiB (#394).

Design: docs/MESH_DESIGN.md ("Replication").
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import random
from typing import Any

import mesh_beacon as mb
import mesh_membership as mem
import mesh_model as mm
import peer_protocol as pp
from mesh_ports import Clock, TimerHandle
from mesh_rpc import RpcRouter
from mesh_state import Accept, MeshState, ViewPublisher

MAX_REPLY_BYTES = 100 * 1024
MAX_SYNC_ROUNDS = 16


@dataclass
class SyncConfig:
    push_delay_s: tuple[float, float] = (0.05, 0.10)
    repair_s: tuple[float, float] = (5.0, 10.0)
    request_timeout_s: float = 2.0
    backoff_base_s: float = 0.2
    backoff_max_s: float = 10.0
    disabled_caps_by_peer: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass
class SyncStats:
    syncs: int = 0
    pushes: int = 0
    pulls_on_hint: int = 0
    records_accepted: int = 0
    records_stale: int = 0
    records_rejected: int = 0
    malformed: int = 0
    failures: int = 0
    same_hash: int = 0
    compatibility_refusals: int = 0


class _Link:
    __slots__ = ("node_id", "inflight", "want_sync", "want_push", "failures",
                 "next_ok", "timer", "sync_rounds")

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.inflight = False
        self.want_sync = False
        self.want_push = False
        self.failures = 0
        self.next_ok = 0.0
        self.timer: TimerHandle | None = None
        self.sync_rounds = 0


def _wire_records(records: list[mm.NodeRecord], budget: int) -> tuple[list[dict[str, Any]], bool]:
    """Pack records into at most *budget* encoded bytes. Returns (wire, more)."""
    packed: list[dict[str, Any]] = []
    used = 0
    for index, record in enumerate(records):
        size = mm.encoded_size(record) + 1
        if packed and used + size > budget:
            return packed, True
        packed.append(record.to_wire())
        used += size
        if used > budget and index + 1 < len(records):
            return packed, True
    return packed, False


class Replicator:
    def __init__(self, *, clock: Clock, rpc: RpcRouter, rng: random.Random,
                 beacon: mb.Beacon, membership: mem.Membership, state: MeshState,
                 publisher: ViewPublisher, config: SyncConfig | None = None) -> None:
        self._clock = clock
        self._rpc = rpc
        self._rng = rng
        self._beacon = beacon
        self._membership = membership
        self._state = state
        self._publisher = publisher
        self.config = config or SyncConfig()
        self.stats = SyncStats()
        self.hello = pp.local_handshake(state.own.version)
        self.agreements: dict[str, pp.Agreement] = {}
        self._links: dict[str, _Link] = {}
        self._push_timer: TimerHandle | None = None
        self._repair_timer: TimerHandle | None = None
        self._started = False
        self._closed = False
        rpc.register("sync", self._on_sync, protected=True)
        rpc.register("push", self._on_push, protected=True)

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._started or self._closed:
            return
        self._started = True
        self._schedule_repair()

    def close(self) -> None:
        self._closed = True
        for timer in (self._push_timer, self._repair_timer):
            if timer is not None:
                timer.cancel()
        for link in self._links.values():
            if link.timer is not None:
                link.timer.cancel()
        self._links.clear()
        self.agreements.clear()

    # -- local changes --------------------------------------------------------
    def update(self, **sections: Any) -> mm.NodeRecord:
        """Replace parts of this node's record (targets, clients, sources, edges,
        capabilities, status, ports, addresses); bumps the revision and announces."""
        allowed = {"targets", "clients", "sources", "edges", "capabilities", "status",
                   "mesh_port", "room_port", "addresses", "name", "truncated"}
        unknown = set(sections) - allowed
        if unknown:
            raise ValueError(f"unknown record sections: {sorted(unknown)}")
        own = self._state.own
        local = self._beacon.local
        updated = replace(own, rev=max(own.rev, local.rev) + 1,
                          incarnation=local.incarnation, **sections)
        fitted = mm.fit_record(updated)
        self._state.set_own(fitted)
        self._beacon.update_local(rev=fitted.rev)
        self._publisher.changed()
        self._schedule_push()
        return fitted

    # -- events -----------------------------------------------------------------
    def on_membership_event(self, event: mem.MembershipEvent) -> None:
        if self._closed:
            return
        if isinstance(event, mem.NodeUp):
            self._state.revive(event.node_id, event.boot_id)
            link = self._link(event.node_id)
            link.want_sync = link.want_push = True
            link.failures = 0
            self._pump(link)
            self._publisher.changed()
        elif isinstance(event, mem.NodeDown):
            self._drop_link(event.node_id)
            self._state.drop(event.node_id, event.boot_id)
            self._publisher.changed()
        elif isinstance(event, mem.NodeMoved):
            self._publisher.changed()

    def on_beacon_event(self, event: mb.BeaconEvent) -> None:
        if self._closed:
            return
        if isinstance(event, mb.RevAhead):
            member = self._membership.member(event.node_id)
            if member is not None and member.boot_id == event.boot_id:
                held = self._state.get(event.node_id)
                if held is None or held.boot_id != event.boot_id or held.rev < event.rev:
                    self.stats.pulls_on_hint += 1
                    link = self._link(event.node_id)
                    link.want_sync = True
                    self._pump(link)

    def revoke(self, node_id: str) -> None:
        """Host action: cut a peer off now (it falls back to public discovery only)."""
        self._membership.block(node_id)
        self._drop_link(node_id)
        self._state.drop(node_id)
        self._publisher.changed()

    def refresh_incarnation(self) -> None:
        """Mirror a changed incarnation into the record (called on a timer)."""
        if self._beacon.local.incarnation != self._state.own.incarnation:
            self.update()

    # -- links --------------------------------------------------------------------
    def _link(self, node_id: str) -> _Link:
        link = self._links.get(node_id)
        if link is None:
            link = self._links[node_id] = _Link(node_id)
        return link

    def _drop_link(self, node_id: str) -> None:
        link = self._links.pop(node_id, None)
        self.agreements.pop(node_id, None)
        if link is not None and link.timer is not None:
            link.timer.cancel()

    def _address(self, node_id: str) -> str | None:
        member = self._membership.member(node_id)
        return None if member is None else member.endpoint

    def _pump(self, link: _Link) -> None:
        """Start the next queued request for *link* if allowed."""
        if self._closed or link.inflight:
            return
        now = self._clock.monotonic()
        if now < link.next_ok:
            if link.timer is None:
                link.timer = self._clock.call_later(link.next_ok - now + 0.002,
                                                     lambda: self._wake(link))
            return
        address = self._address(link.node_id)
        if address is None:
            return
        if link.want_sync:
            link.want_sync = False
            link.sync_rounds = 0
            self._send_sync(link, address)
        elif link.want_push:
            link.want_push = False
            self._send_push(link, address, [self._state.own])

    def _wake(self, link: _Link) -> None:
        link.timer = None
        self._pump(link)

    def _failed(self, link: _Link, *, resync: bool) -> None:
        self.stats.failures += 1
        link.failures += 1
        delay = min(self.config.backoff_max_s,
                    self.config.backoff_base_s * (2 ** min(link.failures, 10)))
        link.next_ok = self._clock.monotonic() + delay * (0.5 + self._rng.random())
        if resync:
            link.want_sync = True
        link.inflight = False
        self._pump(link)

    def _succeeded(self, link: _Link) -> None:
        link.failures = 0
        link.inflight = False
        self._pump(link)

    # -- timers ---------------------------------------------------------------------
    def _schedule_push(self) -> None:
        if self._push_timer is not None or self._closed:
            return
        low, high = self.config.push_delay_s
        self._push_timer = self._clock.call_later(
            low + (high - low) * self._rng.random(), self._push_all)

    def _push_all(self) -> None:
        self._push_timer = None
        for member in self._membership.members():
            link = self._link(member.node_id)
            link.want_push = True
            self._pump(link)

    def _schedule_repair(self) -> None:
        low, high = self.config.repair_s
        self._repair_timer = self._clock.call_later(
            low + (high - low) * self._rng.random(), self._repair)

    def _repair(self) -> None:
        if self._closed:
            return
        self.refresh_incarnation()
        peers = self._membership.members()
        if peers:
            member = self._rng.choice(peers)
            link = self._link(member.node_id)
            link.want_sync = True
            self._pump(link)
        self._schedule_repair()

    # -- protocol compatibility -----------------------------------------------------------
    def _agree(self, message: dict[str, Any], *, node_id: str = "") -> pp.Agreement:
        """Negotiate before interpreting any peer state. Missing hello is v1-only."""
        raw = message.get("hello")
        legacy = raw is None
        remote = pp.legacy_handshake() if legacy else pp.parse_handshake(raw)
        return pp.negotiate(
            self.hello, remote, legacy=legacy,
            disabled=self.config.disabled_caps_by_peer.get(node_id, frozenset()),
        )

    def _refused(self) -> dict[str, Any]:
        self.stats.compatibility_refusals += 1
        return {"error": "incompatible_protocol",
                "message": "Older version — some features unavailable with this computer.",
                "hello": self.hello.wire()}

    def _accept_reply(self, link: _Link, value: dict[str, Any]) -> bool:
        """Fail closed if the peer refuses or proposes an incompatible protocol."""
        if value.get("error") is not None:
            self.stats.compatibility_refusals += 1
            self._failed(link, resync=False)
            return False
        try:
            agreement = self._agree(value, node_id=link.node_id)
        except pp.PeerCompatibilityError:
            self.stats.compatibility_refusals += 1
            self._failed(link, resync=False)
            return False
        self.agreements[link.node_id] = agreement
        return True

    # -- requester side ----------------------------------------------------------------
    def _send_sync(self, link: _Link, address: str) -> None:
        link.inflight = True
        self.stats.syncs += 1
        body = {"hello": self.hello.wire(), "hash": self._state.digest_hash(),
                "digest": {node: [boot, rev] for node, (boot, rev)
                           in self._state.digest().items()}}

        def reply(value: dict[str, Any] | None, error: str | None) -> None:
            if self._closed or link.node_id not in self._links:
                return
            if value is None:
                self._failed(link, resync=True)
                return
            self._apply_sync_reply(link, address, value)

        self._rpc.call(address, "sync", body, reply, self.config.request_timeout_s)

    def _apply_sync_reply(self, link: _Link, address: str, value: dict[str, Any]) -> None:
        if not self._accept_reply(link, value):
            return
        if value.get("same") is True:
            self.stats.same_hash += 1
            self._succeeded(link)
            return
        self._apply_records(value.get("records"))
        remote: dict[str, tuple[str, int]] = {}
        try:
            remote = mm.parse_digest(value.get("digest", {}))
        except mm.MeshModelError:
            self.stats.malformed += 1
        if value.get("more") is True and link.sync_rounds < MAX_SYNC_ROUNDS:
            link.sync_rounds += 1
            self._send_sync(link, address)
            return
        back = self._state.newer_for(remote) if remote else []
        # Only our own record is authoritative for us; relayed ones are best effort.
        if back:
            self._send_push(link, address, back)
            return
        self._succeeded(link)

    def _send_push(self, link: _Link, address: str, records: list[mm.NodeRecord]) -> None:
        link.inflight = True
        self.stats.pushes += 1
        packed, more = _wire_records(records, MAX_REPLY_BYTES)
        rest = records[len(packed):] if more else []

        def reply(value: dict[str, Any] | None, error: str | None) -> None:
            if self._closed or link.node_id not in self._links:
                return
            if value is None:
                self._failed(link, resync=True)
                return
            if not self._accept_reply(link, value):
                return
            if rest:
                self._send_push(link, address, rest)
                return
            self._succeeded(link)

        self._rpc.call(address, "push", {"hello": self.hello.wire(), "records": packed}, reply,
                       self.config.request_timeout_s)

    # -- shared acceptance ---------------------------------------------------------------
    def _apply_records(self, raw: object) -> int:
        if not isinstance(raw, list):
            return 0
        accepted = 0
        for item in raw[:mm.MAX_NODES]:
            try:
                record = mm.parse_record(item)
            except mm.MeshModelError:
                self.stats.malformed += 1
                continue
            member = self._membership.member(record.node_id)
            current = member.boot_id if member is not None else None
            if member is None and record.node_id != self._state.own.node_id:
                self.stats.records_rejected += 1       # not (yet) a live member
                continue
            result = self._state.accept(record, current_boot=current)
            if result is Accept.ACCEPTED:
                accepted += 1
                self.stats.records_accepted += 1
            elif result in {Accept.STALE, Accept.SAME}:
                self.stats.records_stale += 1
            elif result is not Accept.OWN:
                self.stats.records_rejected += 1
        if accepted:
            self._publisher.changed()
        return accepted

    # -- responder side ------------------------------------------------------------------
    def _on_sync(self, _source: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self._agree(body)
        except pp.PeerCompatibilityError:
            return self._refused()
        mine = self._state.digest()
        if body.get("hash") == mm.digest_hash(mine):
            return {"same": True, "hello": self.hello.wire()}
        try:
            remote = mm.parse_digest(body.get("digest", {}))
        except mm.MeshModelError:
            self.stats.malformed += 1
            return {"same": False, "hello": self.hello.wire(),
                    "records": [], "digest": _digest_wire(mine)}
        wanted = self._state.newer_for(remote)
        packed, more = _wire_records(wanted, MAX_REPLY_BYTES)
        return {"same": False, "hello": self.hello.wire(),
                "records": packed, "more": more,
                "digest": _digest_wire(mine)}

    def _on_push(self, _source: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self._agree(body)
        except pp.PeerCompatibilityError:
            return self._refused()
        accepted = self._apply_records(body.get("records"))
        return {"accepted": accepted, "hello": self.hello.wire()}


def _digest_wire(digest: dict[str, tuple[str, int]]) -> dict[str, list[Any]]:
    return {node: [boot, rev] for node, (boot, rev) in digest.items()}


__all__ = ["Replicator", "SyncConfig", "SyncStats"]
