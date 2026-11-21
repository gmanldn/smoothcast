"""A minimal ``NodeUnderTest`` built on the presence beacon (for tests of #396)."""
from __future__ import annotations

from pathlib import Path
import random
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_beacon as mb
import mesh_model as mm


class BeaconNode:
    """Alive = heard within ``ALIVE_FOR`` seconds and not said goodbye."""

    ALIVE_FOR = 3.5

    def __init__(self, *, node_id: str, boot_id: str, name: str, clock: Any,
                 transport: Any, rng: random.Random, boot_epoch: int,
                 seeds: tuple[str, ...] = (), config: mb.BeaconConfig | None = None) -> None:
        self.node_id = node_id
        self._clock = clock
        self._targets: dict[str, mm.TargetObservation] = {}
        self.events: list[mb.BeaconEvent] = []
        self.duplicates: list[mb.DuplicateIdentity] = []
        self._peers: dict[str, list[Any]] = {}      # id -> [boot_id, rev, last_beat]
        self.local = mb.LocalState(node_id, boot_id, boot_epoch, 8801, rev=1)
        cfg = config or mb.BeaconConfig(seeds=tuple(seeds))
        self.beacon = mb.Beacon(clock=clock, transport=transport, rng=rng,
                                local=self.local, on_event=self._on_event, config=cfg)

    def _on_event(self, event: mb.BeaconEvent) -> None:
        self.events.append(event)
        now = self._clock.monotonic()
        if isinstance(event, mb.PeerSeen):
            self._peers[event.node_id] = [event.boot_id, event.rev, now]
        elif isinstance(event, mb.PeerBeat):
            known = self._peers.get(event.node_id)
            if known is not None and known[0] == event.boot_id:
                known[1] = max(known[1], event.rev)
                known[2] = now
        elif isinstance(event, mb.PeerGone):
            known = self._peers.get(event.node_id)
            if known is not None and known[0] == event.boot_id:
                del self._peers[event.node_id]
        elif isinstance(event, mb.DuplicateIdentity):
            self.duplicates.append(event)

    def start(self) -> None:
        self.beacon.start()

    def stop(self, clean: bool) -> None:
        self.beacon.close(graceful=clean)

    def on_wake(self) -> None:
        self.beacon.notify_wake()

    def on_address_changed(self) -> None:
        self.beacon.notify_address_changed()

    def local_key(self) -> tuple[str, int]:
        return (self.local.boot_id, self.local.rev)

    def records(self) -> dict[str, tuple[str, int]]:
        now = self._clock.monotonic()
        digest = {node: (boot, rev) for node, (boot, rev, seen) in self._peers.items()
                  if now - seen <= self.ALIVE_FOR}
        digest[self.node_id] = self.local_key()
        return digest

    def target_ids(self) -> set[str]:
        return set(self._targets)

    def add_target(self, target: mm.TargetObservation) -> None:
        self._targets[target.id] = target
        self.beacon.update_local(rev=self.local.rev + 1)
