"""``NodeUnderTest`` with the full mesh stack: beacon, membership, replication, view."""
from __future__ import annotations

from pathlib import Path
import random
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_beacon as mb
import mesh_membership as mem
import mesh_model as mm
import mesh_state as ms_
import mesh_sync as sync
from mesh_policy import MeshPolicy
from mesh_rpc import RpcRouter


class FullNode:
    def __init__(self, *, node_id: str, boot_id: str, name: str, clock: Any,
                 transport: Any, rng: random.Random, boot_epoch: int,
                 seeds: tuple[str, ...] = (), hook_wake: bool = True, strict: bool = False,
                 sync_config: sync.SyncConfig | None = None) -> None:
        self.node_id = node_id
        self._clock = clock
        self._transport = transport
        self._hook_wake = hook_wake
        self.membership_events: list[mem.MembershipEvent] = []
        self.local = mb.LocalState(node_id, boot_id, boot_epoch, 8801, rev=1)
        own = mm.NodeRecord(node_id=node_id, boot_id=boot_id, name=name, version="1.2.0",
                            rev=1, boot_epoch=boot_epoch, mesh_port=8801,
                            capabilities=("room",), addresses=(transport.address,))
        self.policy = MeshPolicy(
            strict=strict, member_addresses=lambda: [m.address for m in self.membership.members()],
            is_blocked=lambda a: self.membership.is_blocked_address(a))
        self.rpc = RpcRouter(transport, authorize=self.policy.allow, clock=clock)
        self.beacon = mb.Beacon(clock=clock, transport=transport, rng=rng, local=self.local,
                                on_event=self._on_beacon,
                                config=mb.BeaconConfig(seeds=tuple(seeds)))
        self.membership = mem.Membership(clock=clock, rpc=self.rpc, rng=rng,
                                         beacon=self.beacon, on_event=self._on_membership)
        self.state = ms_.MeshState(own, clock=clock)
        self.publisher = ms_.ViewPublisher(
            clock=clock, state=self.state, is_alive=lambda n: self.membership.member(n) is not None)
        self.replicator = sync.Replicator(
            clock=clock, rpc=self.rpc, rng=rng, beacon=self.beacon,
            membership=self.membership, state=self.state, publisher=self.publisher,
            config=sync_config)

    def _on_beacon(self, event: mb.BeaconEvent) -> None:
        self.membership.on_beacon_event(event)
        self.replicator.on_beacon_event(event)

    def _on_membership(self, event: mem.MembershipEvent) -> None:
        self.membership_events.append(event)
        self.replicator.on_membership_event(event)
        self.publisher.changed()

    # -- NodeUnderTest ----------------------------------------------------------
    def start(self) -> None:
        self.beacon.start()
        self.membership.start()
        self.replicator.start()

    def stop(self, clean: bool) -> None:
        self.replicator.close()
        self.membership.close()
        self.publisher.close()
        self.beacon.close(graceful=clean)

    def on_wake(self) -> None:
        if self._hook_wake:
            self.membership.notify_wake()

    def on_address_changed(self) -> None:
        self.beacon.notify_address_changed()
        self.replicator.update(addresses=(self._transport.address,))

    def local_key(self) -> tuple[str, int]:
        return (self.local.boot_id, self.state.own.rev)

    def records(self) -> dict[str, tuple[str, int]]:
        return self.publisher.view.digest()

    def target_ids(self) -> set[str]:
        return {target.id for _node, target in self.publisher.view.targets()}

    def add_target(self, target: mm.TargetObservation) -> None:
        current = {t.id: t for t in self.state.own.targets}
        current[target.id] = target
        self.replicator.update(targets=tuple(current.values()))
