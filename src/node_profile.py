"""Plain-language profile of one mesh node: its nature, reach and attachments (#710). GTK-free.

Built only from a validated ``NodeRecord`` so the GTK Network pane, the web pane
and the diagram show the same facts. Nothing is dropped: every target, client,
source and measured edge on the record appears in the profile.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

CAPABILITY_TEXT = {
    "relay": "Relays media for other nodes", "transcode": "Transcodes video",
    "library": "Shares a media library", "cast": "Casts to Chromecast",
    "dlna": "Casts to DLNA", "screen": "Hosts browser screens",
    "portal": "Serves the room web page", "files": "Serves files to peers",
}


@dataclass(frozen=True)
class Link:
    peer: str
    peer_kind: str            # node | target
    healthy: bool
    text: str                 # "12 ms" / "last worked 4 s ago" / reason


@dataclass(frozen=True)
class NodeProfile:
    node_id: str
    name: str
    role: str                 # This device | Primary | Node | Leaving
    version: str
    capabilities: tuple[str, ...]
    addresses: tuple[str, ...]
    ports: str
    targets: tuple[str, ...]
    clients: tuple[str, ...]
    sources: tuple[str, ...]
    links: tuple[Link, ...]
    headline: str


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _link(edge) -> Link:
    if edge.reason:
        return Link(edge.peer, edge.peer_kind, False, f"failing: {edge.reason}")
    if edge.last_ok_ms is None:
        return Link(edge.peer, edge.peer_kind, False, "never reached")
    rtt = f"{edge.rtt_ms} ms" if edge.rtt_ms is not None else "reachable"
    return Link(edge.peer, edge.peer_kind, True, rtt)


def profile(record, *, local_id: str | None = None, primary_id: str | None = None) -> NodeProfile:
    if record.status == "draining":
        role = "Leaving"
    elif record.node_id == local_id:
        role = "This device"
    elif record.node_id == primary_id:
        role = "Primary"
    else:
        role = "Node"
    caps = tuple(CAPABILITY_TEXT.get(c, c.replace("-", " ").capitalize())
                 for c in sorted(record.capabilities))
    ports = ", ".join(p for p in (f"mesh {record.mesh_port}" if record.mesh_port else "",
                                  f"room {record.room_port}" if record.room_port else "") if p)
    targets = tuple(f"{t.name} ({t.kind}, {t.state})" for t in
                    sorted(record.targets, key=lambda t: t.name.casefold()))
    clients = tuple(f"{c.name or c.role} ({c.role})" for c in
                    sorted(record.clients, key=lambda c: (c.name or c.role).casefold()))
    sources = tuple(f"{s.count} {s.kind} file{'' if s.count == 1 else 's'}"
                    + (f" · {', '.join(s.formats)}" if s.formats else "") for s in record.sources)
    links = tuple(_link(e) for e in sorted(record.edges, key=lambda e: (e.peer_kind, e.peer)))
    headline = (f"v{record.version} · {_plural(len(record.targets), 'target')} · "
                f"{_plural(len(record.clients), 'client')}")
    return NodeProfile(record.node_id, record.name, role, record.version, caps,
                       tuple(record.addresses), ports, targets, clients, sources, links, headline)


def redact(record):
    """Guest-tier view of a record: no addresses, edges, sources or client names."""
    anon = tuple(dataclasses.replace(c, name="") for c in record.clients)
    return dataclasses.replace(record, addresses=(), edges=(), sources=(), clients=anon)


def as_dict(p: NodeProfile) -> dict:
    d = dataclasses.asdict(p)
    d["links"] = [dataclasses.asdict(link) for link in p.links]
    return d
