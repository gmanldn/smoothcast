"""Replicated mesh state and the read model built on it (ticket #398, "M5").

``MeshState`` holds one record per node under the *single writer* rule: a record
replaces the held one only if it is strictly newer for the same boot, or belongs
to the owner's current boot. Because every record has exactly one writer there
are no conflicts to merge. ``MeshView`` is the immutable snapshot everyone else
(GTK, web, routing, roles) reads; ``ViewPublisher`` turns state changes into
coalesced ``Delta`` objects with bounded per-subscriber queues, so a slow
consumer is dropped to a full ``Snapshot`` and can never grow memory.

GTK-free and clock-injectable. Design: docs/MESH_DESIGN.md ("Replication").
"""
from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib

import mesh_model as mm
from mesh_ports import Clock, TimerHandle

DEAD_BOOT_MEMORY = 128
DEAD_BOOT_TTL_S = 60.0
SECTIONS = ("node", "targets", "clients", "sources", "edges")


class Accept(Enum):
    ACCEPTED = "accepted"
    SAME = "same"                   # identical revision already held
    STALE = "stale"                 # older revision of the held boot
    OLD_BOOT = "old_boot"           # a boot the owner is no longer running
    DEAD = "dead"                   # owner (this boot) was declared dead/gone
    FULL = "full"                   # node-count or size cap refuses a new node
    OWN = "own"                     # about this very node; never overwritten by peers


class MeshState:
    """Records of every known node, own record included."""

    def __init__(self, own: mm.NodeRecord, *, clock: Clock) -> None:
        self._clock = clock
        self._own = own
        self._records: dict[str, mm.NodeRecord] = {}
        self._dead: OrderedDict[tuple[str, str], float] = OrderedDict()
        self.version = 0                    # bumps on every change

    # -- own record -----------------------------------------------------------
    @property
    def own(self) -> mm.NodeRecord:
        return self._own

    def set_own(self, record: mm.NodeRecord) -> None:
        if record.node_id != self._own.node_id or record.boot_id != self._own.boot_id:
            raise ValueError("own record must keep this node's identity")
        if record.rev < self._own.rev:
            raise ValueError("own revision must not go backwards")
        self._own = record
        self.version += 1

    # -- reads ----------------------------------------------------------------
    def get(self, node_id: str) -> mm.NodeRecord | None:
        if node_id == self._own.node_id:
            return self._own
        return self._records.get(node_id)

    def records(self) -> dict[str, mm.NodeRecord]:
        merged = dict(self._records)
        merged[self._own.node_id] = self._own
        return merged

    def digest(self) -> dict[str, tuple[str, int]]:
        return mm.digest_of(self.records().values())

    def digest_hash(self) -> str:
        return mm.digest_hash(self.digest())

    def newer_for(self, remote: Mapping[str, tuple[str, int]]) -> list[mm.NodeRecord]:
        """Records the holder of *remote* lacks or may hold an older version of.

        A differing boot id is sent too: the receiver decides which boot is
        current, because boot ids are not ordered.
        """
        wanted = []
        for node_id, record in sorted(self.records().items()):
            held = remote.get(node_id)
            if held is None or held[0] != record.boot_id or held[1] < record.rev:
                wanted.append(record)
        return wanted

    # -- writes ----------------------------------------------------------------
    def _expire_dead(self) -> None:
        now = self._clock.monotonic()
        for key, stamp in list(self._dead.items()):
            if now - stamp > DEAD_BOOT_TTL_S:
                del self._dead[key]

    def accept(self, record: mm.NodeRecord, *, current_boot: str | None) -> Accept:
        """Apply a peer's record. *current_boot* is the owner's boot according to
        membership (``None`` if membership does not know the node yet)."""
        if record.node_id == self._own.node_id:
            return Accept.OWN
        self._expire_dead()
        if (record.node_id, record.boot_id) in self._dead:
            return Accept.DEAD
        if current_boot is not None and record.boot_id != current_boot:
            return Accept.OLD_BOOT
        held = self._records.get(record.node_id)
        if held is not None:
            if held.boot_id == record.boot_id:
                if record.rev < held.rev:
                    return Accept.STALE
                if record.rev == held.rev:
                    return Accept.SAME
            elif current_boot is None and (record.boot_epoch, record.boot_id) <= (
                    held.boot_epoch, held.boot_id):
                return Accept.OLD_BOOT          # unverified older boot
        elif mm.would_exceed_mesh_limits(self.records(), record):
            return Accept.FULL
        self._records[record.node_id] = record
        self.version += 1
        return Accept.ACCEPTED

    def drop(self, node_id: str, boot_id: str | None = None) -> bool:
        """The owner is gone: forget its record and refuse that boot for a while."""
        held = self._records.pop(node_id, None)
        boot = boot_id or (held.boot_id if held is not None else None)
        if boot is not None:
            self._dead[(node_id, boot)] = self._clock.monotonic()
            self._dead.move_to_end((node_id, boot))
            while len(self._dead) > DEAD_BOOT_MEMORY:
                self._dead.popitem(last=False)
        if held is not None:
            self.version += 1
        return held is not None

    def revive(self, node_id: str, boot_id: str) -> None:
        """Membership saw the node alive again (first-hand): lift the refusal."""
        self._dead.pop((node_id, boot_id), None)


# ---------------------------------------------------------------------------
# Read model


@dataclass(frozen=True)
class MeshView:
    generation: int
    local_id: str
    nodes: tuple[mm.NodeRecord, ...]        # sorted by node_id; includes this node

    def node(self, node_id: str) -> mm.NodeRecord | None:
        for record in self.nodes:
            if record.node_id == node_id:
                return record
        return None

    def targets(self) -> list[tuple[str, mm.TargetObservation]]:
        """Every (observing node id, target observation) pair."""
        return [(record.node_id, target) for record in self.nodes
                for target in record.targets]

    def digest(self) -> dict[str, tuple[str, int]]:
        return mm.digest_of(self.nodes)

    def digest_hash(self) -> str:
        return mm.digest_hash(self.digest())

    def fingerprint(self) -> str:
        """Content hash: equal views on two nodes have equal fingerprints."""
        digest = hashlib.sha256()
        for record in self.nodes:
            digest.update(mm.record_digest(record).encode("ascii"))
        return digest.hexdigest()


@dataclass(frozen=True)
class MeshChange:
    kind: str                               # "added" | "removed" | "updated"
    node_id: str
    sections: tuple[str, ...] = ()          # for "updated": what changed


@dataclass(frozen=True)
class Delta:
    generation: int
    changes: tuple[MeshChange, ...]


@dataclass(frozen=True)
class Snapshot:
    view: MeshView


def diff_views(old: MeshView | None, new: MeshView) -> tuple[MeshChange, ...]:
    previous = {r.node_id: r for r in old.nodes} if old is not None else {}
    current = {r.node_id: r for r in new.nodes}
    changes: list[MeshChange] = []
    for node_id in sorted(set(previous) | set(current)):
        before, after = previous.get(node_id), current.get(node_id)
        if before is None:
            changes.append(MeshChange("added", node_id, SECTIONS))
        elif after is None:
            changes.append(MeshChange("removed", node_id))
        elif before != after:
            sections = []
            if (before.boot_id, before.incarnation, before.name, before.version,
                    before.capabilities, before.status, before.mesh_port,
                    before.room_port, before.addresses, before.boot_epoch) != (
                    after.boot_id, after.incarnation, after.name, after.version,
                    after.capabilities, after.status, after.mesh_port,
                    after.room_port, after.addresses, after.boot_epoch):
                sections.append("node")
            for name in ("targets", "clients", "sources", "edges"):
                if getattr(before, name) != getattr(after, name):
                    sections.append(name)
            changes.append(MeshChange("updated", node_id, tuple(sections) or ("node",)))
    return tuple(changes)


class Subscription:
    """Bounded queue of deltas. Overflow is replaced by one fresh snapshot."""

    def __init__(self, publisher: ViewPublisher, limit: int,
                 on_ready: Callable[[], None] | None) -> None:
        self._publisher = publisher
        self._limit = limit
        self._on_ready = on_ready
        self._queue: deque[Delta] = deque()
        self._overflow = True               # a new subscriber starts from a snapshot
        self.closed = False
        self.overflows = 0

    def _offer(self, delta: Delta) -> None:
        if self.closed:
            return
        was_idle = self.pending == 0
        if self._overflow:
            pass                            # a snapshot is already owed
        elif len(self._queue) >= self._limit:
            self._queue.clear()
            self._overflow = True
            self.overflows += 1
        else:
            self._queue.append(delta)
        if was_idle:
            self._notify()

    def _notify(self) -> None:
        if self._on_ready is not None:
            try:
                self._on_ready()
            except Exception:  # noqa: BLE001 - a bad ready callback must not stop the state machine
                pass

    def poll(self) -> list[Delta | Snapshot]:
        """Drain pending items: deltas in order, or a single full snapshot."""
        if self.closed:
            return []
        if self._overflow:
            self._overflow = False
            self._queue.clear()
            return [Snapshot(self._publisher.view)]
        items: list[Delta | Snapshot] = list(self._queue)
        self._queue.clear()
        return items

    @property
    def pending(self) -> int:
        return len(self._queue) + (1 if self._overflow else 0)

    def close(self) -> None:
        self.closed = True
        self._queue.clear()
        self._publisher._unsubscribe(self)


class ViewPublisher:
    """Builds ``MeshView`` snapshots from state + liveness and publishes deltas.

    Only nodes that membership reports alive (plus this node) appear in the view,
    so a record held for a node that has since died never leaks into the UI.
    """

    def __init__(self, *, clock: Clock, state: MeshState,
                 is_alive: Callable[[str], bool], coalesce_s: float = 0.05,
                 max_subscribers: int = 64) -> None:
        self._clock = clock
        self._state = state
        self._is_alive = is_alive
        self._coalesce_s = coalesce_s
        self._max_subscribers = max_subscribers
        self._subscribers: list[Subscription] = []
        self._timer: TimerHandle | None = None
        self._closed = False
        self._view = self._build(0)
        self.publications = 0

    @property
    def view(self) -> MeshView:
        return self._view

    def _build(self, generation: int) -> MeshView:
        own = self._state.own.node_id
        nodes = tuple(sorted(
            (r for node_id, r in self._state.records().items()
             if node_id == own or self._is_alive(node_id)),
            key=lambda r: r.node_id))
        return MeshView(generation, own, nodes)

    def changed(self) -> None:
        """State or liveness changed: publish soon, coalescing bursts."""
        if self._closed or self._timer is not None:
            return
        self._timer = self._clock.call_later(self._coalesce_s, self._publish)

    def flush(self) -> MeshView:
        """Publish immediately (tests, shutdown)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._publish()
        return self._view

    def _publish(self) -> None:
        self._timer = None
        candidate = self._build(self._view.generation + 1)
        changes = diff_views(self._view, candidate)
        if not changes:
            return
        self._view = candidate
        self.publications += 1
        delta = Delta(candidate.generation, changes)
        for subscription in list(self._subscribers):
            subscription._offer(delta)

    def subscribe(self, *, limit: int = 64,
                  on_ready: Callable[[], None] | None = None) -> Subscription:
        if len(self._subscribers) >= self._max_subscribers:
            raise OverflowError("too many mesh subscribers")
        subscription = Subscription(self, max(1, limit), on_ready)
        self._subscribers.append(subscription)
        subscription._notify()
        return subscription

    def _unsubscribe(self, subscription: Subscription) -> None:
        if subscription in self._subscribers:
            self._subscribers.remove(subscription)

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for subscription in list(self._subscribers):
            subscription.close()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def records_equal(a: Iterable[mm.NodeRecord], b: Iterable[mm.NodeRecord]) -> bool:
    return sorted(mm.record_digest(r) for r in a) == sorted(mm.record_digest(r) for r in b)


__all__ = [
    "Accept", "Delta", "MeshChange", "MeshState", "MeshView", "Snapshot", "Subscription",
    "ViewPublisher", "diff_views", "records_equal",
]
