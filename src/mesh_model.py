"""Versioned, bounded wire model for the SmoothCast mesh (ticket #394, "M1").

GTK-free and I/O-free. Every later mesh layer (presence beacon, membership,
replication, cache, UI, browser push) shares the records defined here, so
untrusted input is validated in exactly one place.

Rules that hold for everything in this module:

* **Parse strictly, build tolerantly.** ``parse_*`` raise only
  :class:`MeshModelError` and never allocate beyond the caps below. Builders
  (:func:`fit_record`) shrink an oversized local record by dropping the least
  valuable entries and set ``truncated``.
* **Canonical encoding.** :func:`encode_record` and :func:`record_digest` are
  identical across platforms and Python versions: sorted keys and lists,
  ASCII-escaped JSON, integers only (times are millisecond/second integers,
  never floats, never absolute wall clock for relative ages).
* **Single writer.** A record is owned by ``node_id``. ``(boot_id, rev)`` order
  records of one owner; consumers decide acceptance (ticket #398).
* **Tiers.** :func:`public_tier`, :func:`guest_tier` and :func:`full_tier` are the
  only way to serialise a record for a given audience. Which audience a peer
  belongs to is a policy decision (see docs/VISION.md, trusted home LAN);
  this module only guarantees each tier's allow-list.

Design: docs/MESH_DESIGN.md.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import hashlib
import ipaddress
import json
import re
import unicodedata
from typing import Any

PROTOCOL_VERSION = 1
SUPPORTED_PROTOCOLS: tuple[int, ...] = (1,)

MAX_RECORD_BYTES = 16 * 1024
MAX_MESH_BYTES = 512 * 1024
MAX_NODES = 64
MAX_TARGETS = 64
MAX_CLIENTS = 64
MAX_EDGES = 128
MAX_SOURCES = 16
MAX_CAPABILITIES = 32
MAX_ADDRESSES = 8
MAX_FORMATS = 16
MAX_FLAGS = 8
MAX_PROTOCOLS = 8
MAX_NAME = 48
MAX_MODEL = 64

TARGET_KINDS = frozenset({"cast", "dlna", "screen", "smoothcast"})
TARGET_STATES = frozenset({"ready", "busy", "stale", "unreachable"})
CLIENT_ROLES = frozenset({"controller", "screen", "speaker"})
SOURCE_KINDS = frozenset({"video", "audio", "mixed"})
EDGE_KINDS = frozenset({"node", "target"})
EDGE_REASONS = frozenset({"", "timeout", "refused", "no_route", "subnet",
                          "tls", "protocol", "other"})
NODE_STATUSES = frozenset({"active", "draining"})

_HEX32 = re.compile(r"^[a-f0-9]{32}$")
_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,95}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_FORMAT = re.compile(r"^[a-z0-9][a-z0-9/.+-]{0,47}$")
_VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
_LAN_NETWORKS = tuple(ipaddress.ip_network(block) for block in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "127.0.0.0/8"))

_MAX_REL_MS = 7 * 24 * 3600 * 1000        # relative ages never exceed a week
_MAX_REL_S = 7 * 24 * 3600
_MAX_EPOCH = 2 ** 40
_MAX_COUNTER = 2 ** 53 - 1                # exact in JSON/JavaScript numbers
_MAX_PORT = 65535


class MeshModelError(ValueError):
    """Untrusted mesh data is malformed, oversized or from an unknown version."""


# ---------------------------------------------------------------------------
# Field validators


def _fail(message: str) -> MeshModelError:
    return MeshModelError(message)


def _obj(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{what} must be an object")
    return value


def _list(value: object, what: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise _fail(f"{what} must be a list")
    if len(value) > limit:
        raise _fail(f"{what} has more than {limit} entries")
    return value


def _int(value: object, what: str, low: int, high: int) -> int:
    # bool is an int subclass and floats such as 3.0 are not integers on the wire.
    if type(value) is not int or not low <= value <= high:
        raise _fail(f"{what} must be an integer from {low} to {high}")
    return value


def _opt_int(value: object, what: str, low: int, high: int) -> int | None:
    return None if value is None else _int(value, what, low, high)


def _clean_ok(text: str) -> bool:
    return all(unicodedata.category(ch) not in {"Cc", "Cs", "Cn", "Zl", "Zp", "Co"}
               for ch in text)


def _text(value: object, what: str, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _fail(f"{what} must be text")
    if len(value) > limit or (not value and not allow_empty):
        raise _fail(f"{what} must be 1 to {limit} characters")
    if value != value.strip() or not _clean_ok(value):
        raise _fail(f"{what} contains unsupported characters")
    return value


def _match(value: object, pattern: re.Pattern[str], what: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _fail(f"{what} is not valid")
    return value


def _enum(value: object, allowed: frozenset[str], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _fail(f"{what} is not a known value")
    return value


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _tokens(value: object, what: str, limit: int, pattern: re.Pattern[str],
            ) -> tuple[str, ...]:
    items = _list(value, what, limit)
    parsed = [_match(item, pattern, what) for item in items]
    if len(set(parsed)) != len(parsed):
        raise _fail(f"{what} contains duplicates")
    return _unique_sorted(parsed)


def clean_text(value: object, limit: int, *, fallback: str = "") -> str:
    """Builder helper: coerce local text into a valid, bounded display string."""
    if not isinstance(value, str):
        return fallback
    kept = "".join(ch if unicodedata.category(ch)[0] != "C"
                   and unicodedata.category(ch) not in {"Zl", "Zp"} else " "
                   for ch in value)
    kept = re.sub(r"\s+", " ", kept).strip()[:limit].strip()
    return kept or fallback


def is_lan_address(value: object) -> bool:
    """True for a numeric IPv4 address in a private, link-local or loopback range."""
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(address in network for network in _LAN_NETWORKS)


# ---------------------------------------------------------------------------
# Records


@dataclass(frozen=True)
class TargetObservation:
    """A playback target one node currently sees (never a command channel)."""

    id: str
    kind: str
    name: str
    state: str = "ready"
    model: str = ""
    formats: tuple[str, ...] = ()
    age_ms: int = 0                 # how long ago this node last saw it
    owner: str = ""                 # advisory node id currently using it

    def to_wire(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name,
                "state": self.state, "model": self.model,
                "formats": list(_unique_sorted(self.formats)),
                "age_ms": self.age_ms, "owner": self.owner}


@dataclass(frozen=True)
class ClientSummary:
    """Aggregate of one web client attached to the owning node."""

    id: str
    role: str
    flags: tuple[str, ...] = ()
    age_s: int = 0
    name: str = ""                  # display name; omitted from some tiers

    def to_wire(self) -> dict[str, Any]:
        return {"id": self.id, "role": self.role,
                "flags": list(_unique_sorted(self.flags)),
                "age_s": self.age_s, "name": self.name}


@dataclass(frozen=True)
class SourceSummary:
    """Capability summary of opted-in shared media: counts only, never paths."""

    kind: str
    count: int
    formats: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, Any]:
        return {"kind": self.kind, "count": self.count,
                "formats": list(_unique_sorted(self.formats))}


@dataclass(frozen=True)
class EdgeObservation:
    """What the owning node measured when reaching a peer node or a target."""

    peer_kind: str
    peer: str
    last_ok_ms: int | None = None   # age of the last success; None = never
    rtt_ms: int | None = None
    reason: str = ""

    def to_wire(self) -> dict[str, Any]:
        return {"peer_kind": self.peer_kind, "peer": self.peer,
                "last_ok_ms": self.last_ok_ms, "rtt_ms": self.rtt_ms,
                "reason": self.reason}


@dataclass(frozen=True)
class NodeRecord:
    """Everything one full node publishes about itself. Single writer."""

    node_id: str
    boot_id: str
    name: str
    version: str = "0.0.0"
    incarnation: int = 0
    rev: int = 0
    boot_epoch: int = 0
    protocols: tuple[int, ...] = (PROTOCOL_VERSION,)
    capabilities: tuple[str, ...] = ()
    status: str = "active"
    mesh_port: int | None = None
    room_port: int | None = None
    addresses: tuple[str, ...] = ()
    targets: tuple[TargetObservation, ...] = ()
    clients: tuple[ClientSummary, ...] = ()
    sources: tuple[SourceSummary, ...] = ()
    edges: tuple[EdgeObservation, ...] = ()
    truncated: bool = False

    @property
    def key(self) -> tuple[str, int]:
        """Ordering handle for this owner's records: ``(boot_id, rev)``."""
        return (self.boot_id, self.rev)

    def to_wire(self) -> dict[str, Any]:
        return _canonical_wire(self)


def _canonical_wire(record: NodeRecord) -> dict[str, Any]:
    targets = sorted(record.targets, key=lambda item: item.id)
    clients = sorted(record.clients, key=lambda item: item.id)
    sources = sorted(record.sources, key=lambda item: item.kind)
    edges = sorted(record.edges, key=lambda item: (item.peer_kind, item.peer))
    return {
        "v": PROTOCOL_VERSION,
        "node_id": record.node_id, "boot_id": record.boot_id,
        "incarnation": record.incarnation, "rev": record.rev,
        "boot_epoch": record.boot_epoch, "name": record.name,
        "version": record.version,
        "protocols": sorted(set(record.protocols)),
        "capabilities": list(_unique_sorted(record.capabilities)),
        "status": record.status,
        "mesh_port": record.mesh_port, "room_port": record.room_port,
        "addresses": list(_unique_sorted(record.addresses)),
        "targets": [item.to_wire() for item in targets],
        "clients": [item.to_wire() for item in clients],
        "sources": [item.to_wire() for item in sources],
        "edges": [item.to_wire() for item in edges],
        "truncated": bool(record.truncated),
    }


# ---------------------------------------------------------------------------
# Strict parsing of untrusted data


def _parse_target(raw: object) -> TargetObservation:
    data = _obj(raw, "target")
    owner = data.get("owner", "")
    if owner != "":
        _match(owner, _HEX32, "target owner")
    return TargetObservation(
        id=_match(data.get("id"), _TARGET_ID, "target id"),
        kind=_enum(data.get("kind"), TARGET_KINDS, "target kind"),
        name=_text(data.get("name"), "target name", MAX_NAME),
        state=_enum(data.get("state"), TARGET_STATES, "target state"),
        model=_text(data.get("model", ""), "target model", MAX_MODEL, allow_empty=True),
        formats=_tokens(data.get("formats", []), "target formats", MAX_FORMATS, _FORMAT),
        age_ms=_int(data.get("age_ms", 0), "target age", 0, _MAX_REL_MS),
        owner=owner,
    )


def _parse_client(raw: object) -> ClientSummary:
    data = _obj(raw, "client")
    return ClientSummary(
        id=_match(data.get("id"), _CLIENT_ID, "client id"),
        role=_enum(data.get("role"), CLIENT_ROLES, "client role"),
        flags=_tokens(data.get("flags", []), "client flags", MAX_FLAGS, _TOKEN),
        age_s=_int(data.get("age_s", 0), "client age", 0, _MAX_REL_S),
        name=_text(data.get("name", ""), "client name", MAX_NAME, allow_empty=True),
    )


def _parse_source(raw: object) -> SourceSummary:
    data = _obj(raw, "source")
    return SourceSummary(
        kind=_enum(data.get("kind"), SOURCE_KINDS, "source kind"),
        count=_int(data.get("count"), "source count", 0, 10_000_000),
        formats=_tokens(data.get("formats", []), "source formats", MAX_FORMATS, _FORMAT),
    )


def _parse_edge(raw: object) -> EdgeObservation:
    data = _obj(raw, "edge")
    kind = _enum(data.get("peer_kind"), EDGE_KINDS, "edge kind")
    peer = data.get("peer")
    _match(peer, _HEX32 if kind == "node" else _TARGET_ID, "edge peer")
    return EdgeObservation(
        peer_kind=kind, peer=str(peer),
        last_ok_ms=_opt_int(data.get("last_ok_ms"), "edge last ok", 0, _MAX_REL_MS),
        rtt_ms=_opt_int(data.get("rtt_ms"), "edge rtt", 0, 600_000),
        reason=_enum(data.get("reason", ""), EDGE_REASONS, "edge reason"),
    )


def _unique(items: list[Any], keyer: Any, what: str) -> tuple[Any, ...]:
    seen = {keyer(item) for item in items}
    if len(seen) != len(items):
        raise _fail(f"{what} contains duplicates")
    return tuple(items)


def parse_record(raw: object) -> NodeRecord:
    """Validate one decoded JSON record. Raises only :class:`MeshModelError`."""
    data = _obj(raw, "record")
    version = _int(data.get("v"), "protocol version", 1, 65535)
    if version not in SUPPORTED_PROTOCOLS:
        raise _fail(f"unsupported mesh protocol version {version}")
    protocols = sorted(set(_int(item, "protocol", 1, 65535)
                           for item in _list(data.get("protocols", [version]),
                                             "protocols", MAX_PROTOCOLS)))
    if not protocols:
        raise _fail("protocols must not be empty")
    addresses = _list(data.get("addresses", []), "addresses", MAX_ADDRESSES)
    for address in addresses:
        if not is_lan_address(address):
            raise _fail("addresses must be numeric private LAN IPv4 addresses")
    if len(set(addresses)) != len(addresses):
        raise _fail("addresses contains duplicates")
    targets = _unique([_parse_target(item) for item in
                       _list(data.get("targets", []), "targets", MAX_TARGETS)],
                      lambda item: item.id, "targets")
    clients = _unique([_parse_client(item) for item in
                       _list(data.get("clients", []), "clients", MAX_CLIENTS)],
                      lambda item: item.id, "clients")
    sources = _unique([_parse_source(item) for item in
                       _list(data.get("sources", []), "sources", MAX_SOURCES)],
                      lambda item: item.kind, "sources")
    edges = _unique([_parse_edge(item) for item in
                     _list(data.get("edges", []), "edges", MAX_EDGES)],
                    lambda item: (item.peer_kind, item.peer), "edges")
    truncated = data.get("truncated", False)
    if type(truncated) is not bool:
        raise _fail("truncated must be true or false")
    record = NodeRecord(
        node_id=_match(data.get("node_id"), _HEX32, "node id"),
        boot_id=_match(data.get("boot_id"), _HEX32, "boot id"),
        name=_text(data.get("name"), "node name", MAX_NAME),
        version=_match(data.get("version"), _VERSION, "software version"),
        incarnation=_int(data.get("incarnation"), "incarnation", 0, _MAX_COUNTER),
        rev=_int(data.get("rev"), "revision", 0, _MAX_COUNTER),
        boot_epoch=_int(data.get("boot_epoch"), "boot epoch", 0, _MAX_EPOCH),
        protocols=tuple(protocols),
        capabilities=_tokens(data.get("capabilities", []), "capabilities",
                             MAX_CAPABILITIES, _TOKEN),
        status=_enum(data.get("status", "active"), NODE_STATUSES, "node status"),
        mesh_port=_opt_int(data.get("mesh_port"), "mesh port", 1, _MAX_PORT),
        room_port=_opt_int(data.get("room_port"), "room port", 1, _MAX_PORT),
        addresses=_unique_sorted(addresses),
        targets=tuple(sorted(targets, key=lambda item: item.id)),
        clients=tuple(sorted(clients, key=lambda item: item.id)),
        sources=tuple(sorted(sources, key=lambda item: item.kind)),
        edges=tuple(sorted(edges, key=lambda item: (item.peer_kind, item.peer))),
        truncated=truncated,
    )
    return record


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("duplicate key in message")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise _fail(f"{name} is not valid JSON")


def decode_json(data: object, *, limit: int = MAX_RECORD_BYTES) -> Any:
    """Decode untrusted bytes/text to JSON within *limit* bytes, safely."""
    if isinstance(data, str):
        data = data.encode("utf-8", "strict")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise _fail("message must be bytes or text")
    if len(data) > limit:
        raise _fail("message is too large")
    try:
        return json.loads(bytes(data).decode("utf-8"),
                          object_pairs_hook=_reject_duplicate_keys,
                          parse_constant=_reject_constant)
    except MeshModelError:
        raise
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise _fail("message is not valid JSON") from exc


def parse_record_bytes(data: object) -> NodeRecord:
    """Decode and validate a record received over the network."""
    return parse_record(decode_json(data))


# ---------------------------------------------------------------------------
# Canonical encoding, digests and size accounting


def canonical_json(value: object) -> bytes:
    """Stable encoding: sorted keys, no whitespace, ASCII, no NaN/Infinity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def encode_record(record: NodeRecord) -> bytes:
    """Canonical bytes for *record*; raises if it exceeds the record cap."""
    encoded = canonical_json(record.to_wire())
    if len(encoded) > MAX_RECORD_BYTES:
        raise _fail("record exceeds the size limit; use fit_record first")
    return encoded


def encoded_size(record: NodeRecord) -> int:
    return len(canonical_json(record.to_wire()))


def record_digest(record: NodeRecord) -> str:
    """SHA-256 of the canonical encoding. Equal records have equal digests."""
    return hashlib.sha256(canonical_json(record.to_wire())).hexdigest()


def digest_of(records: Iterable[NodeRecord]) -> dict[str, tuple[str, int]]:
    """``{node_id: (boot_id, rev)}`` summarising a set of records."""
    return {record.node_id: record.key for record in records}


def digest_hash(digest: Mapping[str, tuple[str, int]]) -> str:
    """One compare to tell whether two nodes hold identical state."""
    flat = [[node, boot, rev] for node, (boot, rev) in sorted(digest.items())]
    return hashlib.sha256(canonical_json(flat)).hexdigest()


def parse_digest(raw: object) -> dict[str, tuple[str, int]]:
    """Validate a digest received from a peer."""
    data = _obj(raw, "digest")
    if len(data) > MAX_NODES:
        raise _fail("digest lists too many nodes")
    parsed: dict[str, tuple[str, int]] = {}
    for node_id, entry in data.items():
        _match(node_id, _HEX32, "digest node id")
        pair = _list(entry, "digest entry", 2)
        if len(pair) != 2:
            raise _fail("digest entry must be [boot_id, rev]")
        parsed[node_id] = (_match(pair[0], _HEX32, "digest boot id"),
                           _int(pair[1], "digest revision", 0, _MAX_COUNTER))
    return parsed


def mesh_size(records: Iterable[NodeRecord]) -> int:
    return sum(encoded_size(record) for record in records)


def would_exceed_mesh_limits(existing: Mapping[str, NodeRecord],
                             incoming: NodeRecord) -> bool:
    """Would admitting *incoming* break the node-count or total-size caps?

    Replacing a node's own record never grows the node count. Consumers refuse
    the newest unknown node first, so an established mesh is never evicted by a
    flood of new identities.
    """
    others = [record for node, record in existing.items() if node != incoming.node_id]
    if len(others) + 1 > MAX_NODES:
        return True
    return mesh_size(others) + encoded_size(incoming) > MAX_MESH_BYTES


def negotiate_protocol(local: Iterable[int], remote: Iterable[int]) -> int:
    """Highest protocol version both sides speak, else :class:`MeshModelError`."""
    try:
        common = {int(v) for v in local} & {int(v) for v in remote}
    except (TypeError, ValueError, OverflowError) as exc:
        raise _fail("protocol list is invalid") from exc
    common = {v for v in common if 1 <= v <= 65535}
    if not common:
        raise _fail("no common mesh protocol version")
    return max(common)


# ---------------------------------------------------------------------------
# Building a record from local data without ever exceeding the caps


def fit_record(record: NodeRecord, *, limit: int = MAX_RECORD_BYTES) -> NodeRecord:
    """Return *record* shrunk to fit caps and *limit*, marking ``truncated``.

    Drop order, least valuable first: edges (largest last-ok age first), client
    names then clients (oldest first), unreachable/stale targets then others
    (oldest first), sources, finally addresses. Identity fields never change.
    """
    changed = False

    def cap(items: tuple[Any, ...], maximum: int, order: Any) -> tuple[Any, ...]:
        nonlocal changed
        if len(items) <= maximum:
            return items
        changed = True
        return tuple(sorted(items, key=order)[:maximum])

    state_rank = {"ready": 0, "busy": 1, "stale": 2, "unreachable": 3}
    targets = cap(record.targets, MAX_TARGETS,
                  lambda t: (state_rank.get(t.state, 4), t.age_ms, t.id))
    clients = cap(record.clients, MAX_CLIENTS, lambda c: (c.age_s, c.id))
    edges = cap(record.edges, MAX_EDGES,
                lambda e: (e.last_ok_ms is None, e.last_ok_ms or 0, e.peer))
    sources = cap(record.sources, MAX_SOURCES, lambda s: s.kind)
    capabilities = cap(tuple(_unique_sorted(record.capabilities)), MAX_CAPABILITIES,
                       lambda c: c)
    addresses = cap(tuple(_unique_sorted(record.addresses)), MAX_ADDRESSES, lambda a: a)
    current = replace(record, targets=targets, clients=clients, edges=edges,
                      sources=sources, capabilities=capabilities, addresses=addresses,
                      truncated=record.truncated or changed)
    while encoded_size(current) > limit:
        if current.edges:
            ordered = sorted(current.edges, key=lambda e: (
                e.last_ok_ms is None, e.last_ok_ms or 0, e.peer))
            current = replace(current, edges=tuple(ordered[:len(ordered) // 2]))
        elif any(c.name for c in current.clients):
            current = replace(current, clients=tuple(
                replace(c, name="") for c in current.clients))
        elif current.clients:
            ordered_c = sorted(current.clients, key=lambda c: (c.age_s, c.id))
            current = replace(current, clients=tuple(ordered_c[:len(ordered_c) // 2]))
        elif current.targets:
            ordered_t = sorted(current.targets, key=lambda t: (
                state_rank.get(t.state, 4), t.age_ms, t.id))
            current = replace(current, targets=tuple(ordered_t[:len(ordered_t) // 2]))
        elif current.sources:
            current = replace(current, sources=())
        else:
            raise _fail("identity fields alone exceed the record size limit")
        current = replace(current, truncated=True)
    return current


# ---------------------------------------------------------------------------
# Audience tiers: the only serialisers other layers should use


def _identity_wire(record: NodeRecord) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION, "node_id": record.node_id, "boot_id": record.boot_id,
        "incarnation": record.incarnation, "rev": record.rev,
        "boot_epoch": record.boot_epoch, "name": record.name,
        "version": record.version, "protocols": sorted(set(record.protocols)),
        "capabilities": list(_unique_sorted(record.capabilities)),
        "status": record.status, "mesh_port": record.mesh_port,
        "room_port": record.room_port,
    }


def public_tier(record: NodeRecord) -> dict[str, Any]:
    """Identity, version and capability names only: safe for any LAN device."""
    return _identity_wire(record)


def guest_tier(record: NodeRecord) -> dict[str, Any]:
    """What a room guest may see of a node: identity plus usable targets.

    No client names or ids, no edges, no sources, no addresses.
    """
    wire = _identity_wire(record)
    wire["targets"] = [item.to_wire() for item in
                       sorted(record.targets, key=lambda item: item.id)]
    wire["client_count"] = len(record.clients)
    return wire


def full_tier(record: NodeRecord) -> dict[str, Any]:
    """The whole record, for peers allowed to see everything (member nodes)."""
    return record.to_wire()


# Names re-exported so callers need only this module.
__all__ = [
    "ClientSummary", "EdgeObservation", "MeshModelError", "NodeRecord",
    "SourceSummary", "TargetObservation", "canonical_json", "clean_text",
    "decode_json", "digest_hash", "digest_of", "encode_record", "encoded_size",
    "fit_record", "full_tier", "guest_tier", "is_lan_address", "mesh_size",
    "negotiate_protocol", "parse_digest", "parse_record", "parse_record_bytes",
    "public_tier", "record_digest", "would_exceed_mesh_limits",
]

