"""Primary media node: deterministic "first node up" succession (ticket #399, "M6").

Every node computes the primary from the same membership view, so no election
messages exist to lose. The primary owns **nothing**: it only provides defaults
(which room a guest who opens the mesh entry address lands in, the mesh name,
advisory tie-breaks). Losing it never blocks another node's rooms, queues or
receivers.

Rule: among eligible live nodes pick the minimum ``(boot_epoch, node_id)``.
Only the *order* of announced values matters, so clock skew between machines
changes which node is first, never whether nodes agree. Hysteresis: a node must
be continuously alive for ``hysteresis_s`` before it can become, or displace,
the primary, so a flapping node cannot make the role bounce. A primary that is
only ``suspect`` keeps the role until it is declared dead. GTK-free.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from mesh_ports import Clock, TimerHandle


@dataclass(frozen=True)
class Candidate:
    node_id: str
    boot_epoch: int
    alive_for_s: float            # continuous time alive in *our* view
    suspect: bool = False


@dataclass(frozen=True)
class PrimaryChanged:
    old: str | None
    new: str | None
    reason: str                   # "first" | "lost" | "older-node" | "none"


def choose_primary(candidates: Iterable[Candidate], current: str | None,
                   hysteresis_s: float = 5.0) -> str | None:
    """Pure decision. Deterministic for equal inputs."""
    nodes = list(candidates)
    if not nodes:
        return None
    by_id = {c.node_id: c for c in nodes}
    eligible = [c for c in nodes
                if c.alive_for_s >= hysteresis_s or c.node_id == current
                or len(nodes) == 1]
    # Suspects may keep the role but never gain it.
    eligible = [c for c in eligible if not c.suspect or c.node_id == current]
    if not eligible:
        eligible = [c for c in nodes if not c.suspect] or nodes
    best = min(eligible, key=lambda c: (c.boot_epoch, c.node_id))
    if current in by_id and current is not None:
        incumbent = by_id[current]
        if (incumbent.boot_epoch, incumbent.node_id) <= (best.boot_epoch, best.node_id):
            return current
    return best.node_id


class PrimaryTracker:
    """Keeps the primary up to date from a membership snapshot function."""

    def __init__(self, *, clock: Clock, own_id: str, own_epoch: int,
                 members: Callable[[], Iterable[tuple[str, str, int, bool]]],
                 on_change: Callable[[PrimaryChanged], None],
                 hysteresis_s: float = 5.0, tick_s: float = 0.5,
                 hint: str | None = None) -> None:
        """*members* yields ``(node_id, boot_id, boot_epoch, suspect)`` for peers."""
        self._clock = clock
        self._own = own_id
        self._own_epoch = own_epoch
        self._members = members
        self._on_change = on_change
        self.hysteresis_s = hysteresis_s
        self._tick = tick_s
        self._since: dict[tuple[str, str], float] = {}
        self._born = clock.monotonic()
        self.primary: str | None = None
        self.hint = hint                  # last primary remembered by the cache (#401)
        self.changes = 0
        self._timer: TimerHandle | None = None
        self._closed = False

    def start(self) -> None:
        self.evaluate()
        self._timer = self._clock.call_later(self._tick, self._loop)

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()

    def _loop(self) -> None:
        if self._closed:
            return
        self.evaluate()
        self._timer = self._clock.call_later(self._tick, self._loop)

    def evaluate(self) -> str | None:
        now = self._clock.monotonic()
        peers = list(self._members())
        live = {(n, b) for n, b, _e, _s in peers}
        for key in list(self._since):
            if key not in live:
                del self._since[key]
        candidates = [Candidate(self._own, self._own_epoch, now - self._born)]
        for node_id, boot_id, epoch, suspect in peers:
            since = self._since.setdefault((node_id, boot_id), now)
            candidates.append(Candidate(node_id, epoch, now - since, suspect))
        chosen = choose_primary(candidates, self.primary, self.hysteresis_s)
        if chosen != self.primary:
            old, self.primary = self.primary, chosen
            self.changes += 1
            reason = ("first" if old is None else "none" if chosen is None else
                      "lost" if old not in {c.node_id for c in candidates} else "older-node")
            try:
                self._on_change(PrimaryChanged(old, chosen, reason))
            except Exception:  # noqa: BLE001 - a bad change listener must not stop election
                pass
        return chosen

    @property
    def is_primary(self) -> bool:
        return self.primary == self._own


__all__ = ["Candidate", "PrimaryChanged", "PrimaryTracker", "choose_primary"]
