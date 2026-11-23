"""Target visibility: what every node sees and can reach (ticket #400, "M7").

Each node publishes the targets it currently sees (Cast, DLNA, SmoothCast,
browser screens) plus bounded reachability edges; every node derives a
``VisibilityMatrix`` (target x node, with freshness) from the replicated view.

**Observation never acts.** This module only *reads* what discovery already
found and, optionally, opens a bare TCP connection to a control port. It never
calls anything that launches, loads, stops or otherwise controls a receiver
(enforced by a static test). Peer-reported facts are *candidates*: the play path
verifies reachability and capability itself before any command (#355/#356).

Ages travel as relative milliseconds, quantised so an unchanged target does not
bump the record revision every refresh. GTK-free. Design: docs/MESH_DESIGN.md.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import random
import socket
from typing import Any

import mesh_model as mm
from mesh_ports import Clock, TimerHandle
from mesh_state import MeshView

READY_S = 30.0               # seen this recently -> ready
EXPIRE_S = 180.0             # not seen for this long -> removed from our record
AGE_QUANTUM_MS = 15_000
PROBE_INTERVAL_S = 15.0
REFRESH_S = 10.0
PROBE_CONCURRENCY = 2
PROBE_TIMEOUT_S = 2.0
EDGE_QUANTUM_MS = 5_000


@dataclass(frozen=True)
class Discovered:
    """One target as reported by the existing Cast/DLNA/screen discovery."""

    id: str
    kind: str
    name: str
    last_seen: float                  # on the injected clock's monotonic scale
    model: str = ""
    formats: tuple[str, ...] = ()
    owner: str = ""                   # advisory: a node currently using it
    busy: bool = False
    probe: tuple[str, int] | None = None   # (address, control port) for reachability


ProbeResult = tuple[bool, int | None, str]            # ok, rtt_ms, failure reason
Prober = Callable[[Discovered, Callable[[ProbeResult], None]], None]


def connect_probe(address: str, port: int, timeout: float = PROBE_TIMEOUT_S) -> ProbeResult:
    """Blocking TCP connect and close: the only network action observation takes.

    Run it off the mesh loop (a worker); tests inject a fake instead.
    """
    import time
    started = time.monotonic()
    try:
        with socket.create_connection((address, port), timeout=timeout):
            pass
    except TimeoutError:
        return False, None, "timeout"
    except ConnectionRefusedError:
        return False, None, "refused"
    except OSError:
        return False, None, "no_route"
    return True, round((time.monotonic() - started) * 1000), ""


class LocalObserver:
    """Builds this node's ``targets``/``edges`` sections and publishes changes."""

    def __init__(self, *, clock: Clock, rng: random.Random,
                 source: Callable[[], Iterable[Discovered]],
                 publish: Callable[..., Any],
                 node_edges: Callable[[], Iterable[tuple[str, float]]] = lambda: (),
                 prober: Prober | None = None,
                 coalesce_s: float = 0.1) -> None:
        """*publish* is ``Replicator.update``; *node_edges* yields (node_id, age_s)."""
        self._clock = clock
        self._rng = rng
        self._source = source
        self._publish = publish
        self._node_edges = node_edges
        self._prober = prober
        self._coalesce = coalesce_s
        self._timer: TimerHandle | None = None
        self._probe_timer: TimerHandle | None = None
        self._tick_timer: TimerHandle | None = None
        self._edges: dict[str, mm.EdgeObservation] = {}
        self._probing: set[str] = set()
        self._unreachable: set[str] = set()
        self._last: tuple[Any, ...] = ()
        self.refreshes = 0
        self.source_calls = 0
        self.probes_started = 0
        self._closed = False

    def start(self) -> None:
        self.refresh()
        self._tick_timer = self._clock.call_later(self._tick_delay(), self._tick)
        if self._prober is not None:
            self._probe_timer = self._clock.call_later(
                PROBE_INTERVAL_S * (0.5 + self._rng.random()), self._probe_round)

    def _tick_delay(self) -> float:
        return REFRESH_S * (0.8 + 0.4 * self._rng.random())

    def _tick(self) -> None:
        """Periodic refresh: ages cross the ready/stale/expiry thresholds on their own."""
        if self._closed:
            return
        self.refresh()
        self._tick_timer = self._clock.call_later(self._tick_delay(), self._tick)

    def close(self) -> None:
        self._closed = True
        for timer in (self._timer, self._probe_timer, self._tick_timer):
            if timer is not None:
                timer.cancel()

    def changed(self) -> None:
        """Discovery saw an arrival/departure: refresh soon (bursts coalesce)."""
        if self._closed or self._timer is not None:
            return
        self._timer = self._clock.call_later(self._coalesce, self.refresh)

    # -- building the record sections --------------------------------------
    def observations(self) -> tuple[mm.TargetObservation, ...]:
        now = self._clock.monotonic()
        self.source_calls += 1
        found: dict[str, mm.TargetObservation] = {}
        for item in self._source():
            age = max(0.0, now - item.last_seen)
            if age > EXPIRE_S:
                continue
            if item.id in self._unreachable:
                state = "unreachable"
            elif age > READY_S:
                state = "stale"
            elif item.busy:
                state = "busy"
            else:
                state = "ready"
            age_ms = 0 if state in {"ready", "busy"} else int(age * 1000) // AGE_QUANTUM_MS * AGE_QUANTUM_MS
            try:
                found[item.id] = mm.TargetObservation(
                    id=item.id, kind=item.kind,
                    name=mm.clean_text(item.name, mm.MAX_NAME, fallback="Unnamed"),
                    state=state, model=mm.clean_text(item.model, mm.MAX_MODEL),
                    formats=tuple(f for f in item.formats[:mm.MAX_FORMATS]
                                  if isinstance(f, str)),
                    age_ms=age_ms, owner=item.owner)
            except Exception:
                continue
        return tuple(sorted(found.values(), key=lambda t: t.id))[:mm.MAX_TARGETS]

    def edges(self) -> tuple[mm.EdgeObservation, ...]:
        out = dict(self._edges)
        for node_id, age_s in self._node_edges():
            quant = int(age_s * 1000) // EDGE_QUANTUM_MS * EDGE_QUANTUM_MS
            out["node:" + node_id] = mm.EdgeObservation("node", node_id, quant)
        return tuple(sorted(out.values(), key=lambda e: (e.peer_kind, e.peer)))[:mm.MAX_EDGES]

    def refresh(self) -> bool:
        """Recompute sections; publish only if something meaningful changed."""
        self._timer = None
        if self._closed:
            return False
        targets, edges = self.observations(), self.edges()
        signature = (targets, edges)
        if signature == self._last:
            return False
        self._last = signature
        self.refreshes += 1
        self._publish(targets=targets, edges=edges)
        return True

    # -- passive reachability probes ------------------------------------------
    def _probe_round(self) -> None:
        if self._closed or self._prober is None:
            return
        for item in self._source():
            if item.probe is None or item.id in self._probing:
                continue
            if len(self._probing) >= PROBE_CONCURRENCY:
                break
            self._probing.add(item.id)
            self.probes_started += 1
            self._prober(item, lambda result, item=item: self._probed(item, result))
        self._probe_timer = self._clock.call_later(
            PROBE_INTERVAL_S * (0.8 + 0.4 * self._rng.random()), self._probe_round)

    def _probed(self, item: Discovered, result: ProbeResult) -> None:
        self._probing.discard(item.id)
        if self._closed:
            return
        ok, rtt, reason = result
        if ok:
            self._unreachable.discard(item.id)
            edge = mm.EdgeObservation("target", item.id, 0, min(rtt or 0, 600_000))
        else:
            self._unreachable.add(item.id)
            prior = self._edges.get(item.id)
            edge = mm.EdgeObservation(
                "target", item.id, prior.last_ok_ms if prior else None, None,
                reason if reason in mm.EDGE_REASONS else "other")
        if len(self._edges) < mm.MAX_EDGES or item.id in self._edges:
            self._edges[item.id] = edge
        self.changed()


# ---------------------------------------------------------------------------
# Aggregation over the replicated view


@dataclass(frozen=True)
class Seen:
    node_id: str
    state: str
    age_ms: int
    rtt_ms: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class TargetEntry:
    id: str
    name: str
    kinds: tuple[str, ...]
    models: tuple[str, ...]
    formats: tuple[str, ...]
    seen_by: tuple[Seen, ...]
    state: str                          # best state across observers
    owner_hint: str = ""

    def ready_nodes(self) -> list[str]:
        return [s.node_id for s in self.seen_by if s.state == "ready"]


_RANK = {"ready": 0, "busy": 1, "stale": 2, "unreachable": 3}


class VisibilityMatrix:
    """Target x node matrix derived from one ``MeshView`` (pure, deterministic)."""

    def __init__(self, view: MeshView) -> None:
        self.view = view
        edges: dict[tuple[str, str], mm.EdgeObservation] = {}
        for record in view.nodes:
            for edge in record.edges:
                if edge.peer_kind == "target":
                    edges[(record.node_id, edge.peer)] = edge
        grouped: dict[str, list[tuple[str, mm.TargetObservation]]] = {}
        for node_id, target in view.targets():
            grouped.setdefault(target.id, []).append((node_id, target))
        self.entries: dict[str, TargetEntry] = {}
        for target_id, rows in grouped.items():
            seen = tuple(sorted(
                (Seen(n, t.state, t.age_ms, getattr(edges.get((n, target_id)), "rtt_ms", None),
                      getattr(edges.get((n, target_id)), "reason", ""))
                 for n, t in rows),
                key=lambda s: (_RANK[s.state], s.rtt_ms is None, s.rtt_ms or 0, s.node_id)))
            names = Counter(t.name for _n, t in rows)
            best_name = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            owners = sorted({t.owner for _n, t in rows
                             if t.owner and t.state in {"ready", "busy"}})
            self.entries[target_id] = TargetEntry(
                id=target_id, name=best_name,
                kinds=tuple(sorted({t.kind for _n, t in rows})),
                models=tuple(sorted({t.model for _n, t in rows if t.model})),
                formats=tuple(sorted({f for _n, t in rows for f in t.formats})),
                seen_by=seen, state=seen[0].state, owner_hint=owners[0] if owners else "")

    def targets(self) -> list[TargetEntry]:
        return sorted(self.entries.values(), key=lambda e: (_RANK[e.state], e.name, e.id))

    def get(self, target_id: str) -> TargetEntry | None:
        return self.entries.get(target_id)

    def node_can_see(self, node_id: str) -> list[str]:
        return sorted(e.id for e in self.entries.values()
                      if any(s.node_id == node_id for s in e.seen_by))


@dataclass(frozen=True)
class RouteCandidate:
    node_id: str
    state: str
    rtt_ms: int | None


@dataclass(frozen=True)
class RouteOptions:
    candidates: tuple[RouteCandidate, ...]
    excluded: tuple[tuple[str, str], ...]       # (node_id, human reason)
    reason: str = ""                            # why nothing works, if empty list


def candidate_routes(matrix: VisibilityMatrix, target_id: str,
                     *, source_node: str | None = None) -> RouteOptions:
    """Nodes that can plausibly drive *target_id*, best first, with exclusions.

    Verification happens at play time; this only orders hypotheses.
    """
    entry = matrix.get(target_id)
    if entry is None:
        return RouteOptions((), (), "No node currently sees that target")
    candidates: list[RouteCandidate] = []
    excluded: list[tuple[str, str]] = []
    for seen in entry.seen_by:
        if seen.state == "ready":
            candidates.append(RouteCandidate(seen.node_id, seen.state, seen.rtt_ms))
        elif seen.state == "busy":
            excluded.append((seen.node_id, "The receiver reports it is busy"))
        elif seen.state == "stale":
            excluded.append((seen.node_id, "Not seen recently"))
        else:
            excluded.append((seen.node_id, f"Unreachable ({seen.reason or 'probe failed'})"))
    if source_node is not None:
        candidates.sort(key=lambda c: (c.node_id != source_node, c.rtt_ms is None,
                                       c.rtt_ms or 0, c.node_id))
    reason = ""
    if not candidates:
        reason = ("The receiver is busy" if any(s.state == "busy" for s in entry.seen_by)
                  else "No node can reach that target right now")
    return RouteOptions(tuple(candidates), tuple(excluded), reason)


__all__ = [
    "Discovered", "LocalObserver", "RouteCandidate", "RouteOptions", "Seen", "TargetEntry",
    "VisibilityMatrix", "candidate_routes", "connect_probe",
]
