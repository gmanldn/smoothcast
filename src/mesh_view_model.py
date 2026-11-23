"""Pure view model for the live Network view (ticket #403, "M10").

Turns a ``MeshView`` (plus the cache's remembered peers and the primary id) into
ordered, stable rows that the GTK window and the tests share. No GTK. Rows carry
*text* for every state (never colour alone), a reason string for anything that is
not ready, and a stable ``key`` so a UI can update rows in place instead of
rebuilding lists, which keeps focus and scroll steady during churn.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import mesh_model as mm
import mesh_visibility as mv
from mesh_state import MeshView

STATE_TEXT = {
    "self": "This device", "ready": "Ready", "busy": "In use", "stale": "Not seen lately",
    "unreachable": "Can't be reached", "cached": "Last seen", "alive": "Online",
    "suspect": "Not responding",
}


@dataclass(frozen=True)
class Row:
    key: str
    kind: str                       # node | client | target
    title: str
    subtitle: str
    badges: tuple[str, ...]
    state: str
    state_text: str
    detail: str = ""                # why it is not ready, in plain words
    seen_by: str = ""


@dataclass(frozen=True)
class NetworkModel:
    nodes: tuple[Row, ...]
    clients: tuple[Row, ...]
    targets: tuple[Row, ...]
    summary: str
    empty_hint: str = ""

    def all_rows(self) -> tuple[Row, ...]:
        return self.nodes + self.clients + self.targets


def relative_age(age_ms: int) -> str:
    seconds = max(0, age_ms // 1000)
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def build_model(view: MeshView, *, primary_id: str | None = None,
                cached_peers: Iterable[tuple[str, str, int]] = (),
                multicast_hint: str = "", show_client_names: bool = True) -> NetworkModel:
    """*cached_peers* is ``(node_id, name, last_seen_epoch_s_ago)`` for remembered nodes."""
    matrix = mv.VisibilityMatrix(view)
    names = {r.node_id: r.name for r in view.nodes}
    live = set(names)

    nodes: list[Row] = []
    for record in view.nodes:
        mine = record.node_id == view.local_id
        badges = []
        if mine:
            badges.append("This device")
        if record.node_id == primary_id:
            badges.append("Primary")
        if record.status == "draining":
            badges.append("Leaving")
        sub = _plural(len(record.targets), "target") + " · " + _plural(len(record.clients), "client")
        nodes.append(Row(f"node:{record.node_id}", "node", record.name, sub, tuple(badges),
                         "self" if mine else "alive", STATE_TEXT["self" if mine else "alive"]))
    for node_id, name, ago_s in cached_peers:
        if node_id in live:
            continue
        nodes.append(Row(f"node:{node_id}", "node", name, relative_age(ago_s * 1000), ("Cached",),
                         "cached", STATE_TEXT["cached"], "Remembered from earlier; not online now."))
    nodes.sort(key=lambda r: (r.state not in {"self"}, r.state == "cached", r.title.casefold(), r.key))

    clients: list[Row] = []
    for record in view.nodes:
        for client in record.clients:
            role = {"controller": "Remote", "screen": "Screen", "speaker": "Speaker"}[client.role]
            title = client.name if (show_client_names and client.name) else role
            badges = (role,) + (("Playing",) if "playing" in client.flags else ())
            clients.append(Row(f"client:{record.node_id}:{client.id}", "client", title,
                               f"via {record.name}", badges, "ready", STATE_TEXT["ready"]))
    clients.sort(key=lambda r: (r.title.casefold(), r.key))

    targets: list[Row] = []
    for entry in matrix.targets():
        options = mv.candidate_routes(matrix, entry.id)
        seen = ", ".join(names.get(s.node_id, "a node") for s in entry.seen_by
                         if s.state == "ready") or ", ".join(
            names.get(s.node_id, "a node") for s in entry.seen_by[:2])
        if entry.state == "ready":
            detail = ""
        elif entry.state == "busy":
            detail = "Another room is using this receiver."
            if entry.owner_hint and entry.owner_hint in names:
                detail = f"In use from {names[entry.owner_hint]}."
        elif entry.state == "stale":
            age = min((s.age_ms for s in entry.seen_by), default=0)
            detail = f"Not seen for {relative_age(age).replace(' ago', '')}."
        else:
            detail = options.reason or "No node can reach it."
        kind = {"cast": "Chromecast", "dlna": "DLNA", "screen": "Browser screen",
                "smoothcast": "SmoothCast"}.get(entry.kinds[0] if entry.kinds else "", "Receiver")
        targets.append(Row(f"target:{entry.id}", "target", entry.name,
                           kind + (f" · {entry.models[0]}" if entry.models and entry.models[0] != kind else ""),
                           (), entry.state, STATE_TEXT[entry.state], detail,
                           f"Seen by {seen}" if seen else ""))
    live_nodes = [r for r in nodes if r.state in {"self", "alive"}]
    ready_targets = sum(1 for t in targets if t.state == "ready")
    summary = (f"{_plural(len(live_nodes), 'device')} · {_plural(len(clients), 'connected client')}"
               f" · {ready_targets} of {_plural(len(targets), 'target')} ready")
    hint = ""
    if len(live_nodes) <= 1 and not targets:
        hint = multicast_hint or "Searching for other SmoothCast devices…"
    return NetworkModel(tuple(nodes), tuple(clients), tuple(targets), summary, hint)


@dataclass(frozen=True)
class RowDiff:
    added: tuple[Row, ...]
    removed: tuple[str, ...]
    changed: tuple[Row, ...]
    order: tuple[str, ...]          # desired key order after applying

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_rows(old: Iterable[Row], new: Iterable[Row]) -> RowDiff:
    """Minimal in-place update plan between two row lists."""
    before = {r.key: r for r in old}
    after = list(new)
    keys = {r.key for r in after}
    return RowDiff(
        added=tuple(r for r in after if r.key not in before),
        removed=tuple(k for k in before if k not in keys),
        changed=tuple(r for r in after if r.key in before and before[r.key] != r),
        order=tuple(r.key for r in after))


def announcement(old: NetworkModel | None, new: NetworkModel) -> str:
    """One short polite live-region sentence for arrivals/departures, or ''."""
    if old is None:
        return ""
    parts = []
    for label, a, b in (("device", old.nodes, new.nodes), ("target", old.targets, new.targets)):
        before = {r.key: r for r in a if r.state not in {"cached"}}
        after = {r.key: r for r in b if r.state not in {"cached"}}
        joined = [after[k].title for k in after if k not in before]
        left = [before[k].title for k in before if k not in after]
        if joined:
            parts.append(f"{', '.join(joined[:2])} joined" if len(joined) <= 2 else
                         f"{len(joined)} {label}s joined")
        if left:
            parts.append(f"{', '.join(left[:2])} left" if len(left) <= 2 else
                         f"{len(left)} {label}s left")
    return "; ".join(parts[:2])


__all__ = ["NetworkModel", "Row", "RowDiff", "announcement", "build_model", "diff_rows",
           "mm", "relative_age"]
