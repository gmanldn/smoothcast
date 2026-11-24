"""Bounded, additive peer handshake and capability agreement (issue #387).

This is protocol *feature* negotiation, separate from mesh_model's record format.
Legacy v1 peers can exchange base records but cannot claim newer capabilities.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Mapping

PROTOCOL = 1
MIN_PROTOCOL = 1
MAX_HANDSHAKE_BYTES = 4096
MAX_STORE_BYTES = 128 * 1024
MAX_CAPABILITIES = 32
_CAP = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")
_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\Z")
# Capabilities are explicit promises, not inferred from a remote app version.
LOCAL_CAPABILITIES = ("mesh.records.v1",)


class PeerCompatibilityError(ValueError):
    """A peer is incompatible or its handshake/schema is malformed."""


@dataclass(frozen=True)
class Handshake:
    proto: int
    min_proto: int
    app_version: str
    caps: tuple[str, ...]

    def wire(self) -> dict:
        return {"proto": self.proto, "min_proto": self.min_proto,
                "app_version": self.app_version, "caps": list(self.caps)}


@dataclass(frozen=True)
class Agreement:
    proto: int
    caps: frozenset[str]
    legacy: bool = False

    def supports(self, capability: str) -> bool:
        return capability in self.caps


def _bounded(value: object, limit: int) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise PeerCompatibilityError("Invalid peer JSON") from exc
    if size > limit:
        raise PeerCompatibilityError("Peer message exceeds limit")


def parse_handshake(value: object) -> Handshake:
    """Ignore future optional keys, but strictly validate required fields."""
    _bounded(value, MAX_HANDSHAKE_BYTES)
    if not isinstance(value, dict):
        raise PeerCompatibilityError("Peer handshake must be an object")
    proto, minimum, version, raw_caps = (value.get(key) for key in
                                         ("proto", "min_proto", "app_version", "caps"))
    if (type(proto) is not int or type(minimum) is not int or
            not 1 <= minimum <= proto <= 65535):
        raise PeerCompatibilityError("Unsupported peer protocol range")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise PeerCompatibilityError("Invalid peer app version")
    if not isinstance(raw_caps, list) or len(raw_caps) > MAX_CAPABILITIES:
        raise PeerCompatibilityError("Invalid peer capabilities")
    if any(not isinstance(cap, str) or len(cap) > 64 or _CAP.fullmatch(cap) is None
           for cap in raw_caps) or len(set(raw_caps)) != len(raw_caps):
        raise PeerCompatibilityError("Invalid peer capabilities")
    return Handshake(proto, minimum, version, tuple(sorted(raw_caps)))


def local_handshake(app_version: str, caps: tuple[str, ...] = LOCAL_CAPABILITIES) -> Handshake:
    return parse_handshake({"proto": PROTOCOL, "min_proto": MIN_PROTOCOL,
                            "app_version": app_version, "caps": list(caps)})


def negotiate(local: Handshake, remote: Handshake, *,
              disabled: frozenset[str] = frozenset(), legacy: bool = False) -> Agreement:
    # An overlap is required; the highest common integer protocol wins.
    lowest = max(local.min_proto, remote.min_proto)
    highest = min(local.proto, remote.proto)
    if lowest > highest:
        raise PeerCompatibilityError("Incompatible peer protocol; update the older computer")
    return Agreement(highest, (frozenset(local.caps) & frozenset(remote.caps)) - disabled,
                     legacy=legacy)


OLDER_VERSION_TEXT = "Older version — some features unavailable with this computer."
INCOMPATIBLE_TEXT = "Incompatible version — update the older computer to use it with this one."


def peer_status_text(agreement: "Agreement | None", wanted: "frozenset[str] | set[str]" = frozenset()) -> str:
    """Plain-language status for a peer row; empty when everything wanted works.

    ``None`` means the handshake was refused as incompatible. A legacy (pre
    negotiation) peer, or one missing a capability we want, is "older version".
    """
    if agreement is None:
        return INCOMPATIBLE_TEXT
    if agreement.legacy or not frozenset(wanted) <= agreement.caps:
        return OLDER_VERSION_TEXT
    return ""


def legacy_handshake() -> Handshake:
    """Old v1 peers understand base records only, never opt-in features."""
    return Handshake(1, 1, "0.0.0", ())


@dataclass(frozen=True)
class StoredDocument:
    """Lossless versioned JSON store; a newer schema is read-only on downgrade."""
    schema: int
    fields: dict
    supported_schema: int

    @property
    def read_only(self) -> bool:
        return self.schema > self.supported_schema

    def wire(self) -> dict:
        return deepcopy(self.fields)

    def update(self, changes: Mapping[str, object]) -> "StoredDocument":
        if self.read_only:
            raise PeerCompatibilityError("Newer peer data is read-only; update SmoothCast")
        if "schema" in changes and changes["schema"] != self.schema:
            raise PeerCompatibilityError("Store schema cannot change via update")
        updated = self.wire()
        updated.update(deepcopy(dict(changes)))
        return parse_store(updated, supported_schema=self.supported_schema)


def parse_store(raw: object, *, supported_schema: int = 1) -> StoredDocument:
    """Retain unknown fields exactly; deny unsupported mutations on downgrade."""
    _bounded(raw, MAX_STORE_BYTES)
    if (not isinstance(raw, dict) or type(raw.get("schema")) is not int
            or not 1 <= raw["schema"] <= 65535):
        raise PeerCompatibilityError("Invalid peer store schema")
    if type(supported_schema) is not int or not 1 <= supported_schema <= 65535:
        raise ValueError("Invalid local schema")
    return StoredDocument(raw["schema"], deepcopy(raw), supported_schema)
