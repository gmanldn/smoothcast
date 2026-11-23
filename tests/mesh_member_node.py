"""``NodeUnderTest`` built on beacon + RPC + membership (for tests of #397)."""
from __future__ import annotations

from pathlib import Path
import random
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_beacon as mb
import mesh_membership as mem
import mesh_model as mm
from mesh_rpc import RpcRouter


class MemberNode:
    def __init__(self, *, node_id: str, boot_id: str, name: str, clock: Any,
                 transport: Any, rng: random.Random, boot_epoch: int,
                 seeds: tuple[str, ...] = (), hook_wake: bool = True,
                 config: mem.MembershipConfig | None = None) -> None:
        self.node_id = node_id
        self.hook_wake = hook_wake
        self._clock = clock
        self._targets: dict[str, mm.TargetObservation] = {}
        self.beacon_events: list[mb.BeaconEvent] = []
        self.events: list[mem.MembershipEvent] = []
        self.regenerated = 0
        self.local = mb.LocalState(node_id, boot_id, boot_epoch, 8801, rev=1)
        self.rpc = RpcRouter(transport)
        self.beacon = mb.Beacon(clock=clock, transport=transport, rng=rng, local=self.local,
                                on_event=self._on_beacon, config=mb.BeaconConfig(seeds=tuple(seeds)))
        self.membership = mem.Membership(
            clock=clock, rpc=self.rpc, rng=rng, beacon=self.beacon,
            on_event=self.events.append, config=config,
            on_regenerate=self._regenerate)

    def _regenerate(self) -> None:
        self.regenerated += 1

    def _on_beacon(self, event: mb.BeaconEvent) -> None:
        self.beacon_events.append(event)
        self.membership.on_beacon_event(event)

    def start(self) -> None:
        self.beacon.start()
        self.membership.start()

    def stop(self, clean: bool) -> None:
        self.membership.close()
        self.beacon.close(graceful=clean)

    def on_wake(self) -> None:
        if self.hook_wake:
            self.membership.notify_wake()

    def on_address_changed(self) -> None:
        self.beacon.notify_address_changed()

    def local_key(self) -> tuple[str, int]:
        return (self.local.boot_id, self.local.rev)

    def records(self) -> dict[str, tuple[str, int]]:
        digest = {m.node_id: (m.boot_id, m.rev) for m in self.membership.members()}
        digest[self.node_id] = self.local_key()
        return digest

    def target_ids(self) -> set[str]:
        return set(self._targets)

    def add_target(self, target: mm.TargetObservation) -> None:
        self._targets[target.id] = target
        self.beacon.update_local(rev=self.local.rev + 1)

    def downs(self) -> list[mem.NodeDown]:
        return [e for e in self.events if isinstance(e, mem.NodeDown)]
