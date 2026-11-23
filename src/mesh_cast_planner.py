"""Pure, conservative Chrome-mesh route suggestions (#564).

No network I/O or receiver commands. Visibility is only an observation; a
returned plan always needs an authoritative preflight and owner lease check.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from mesh_visibility import VisibilityMatrix, candidate_routes

Mode = Literal["direct", "range_proxy", "remux", "transcode", "live_relay"]
SourceKind = Literal["seekable_media", "live_mirror"]
MAX_NODES = 64
MAX_AGE_MS = 5000
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_CODEC = re.compile(r"[a-z0-9_.-]{1,32}\Z")
_COST = {"direct": 0, "range_proxy": 1, "live_relay": 1, "remux": 2, "transcode": 3}
_MESSAGES = {
    "target_missing": "Select a playback target again.",
    "target_busy": "That receiver is already in use. Choose another target.",
    "target_unreachable": "The selected receiver is not reachable right now.",
    "lease_unverified": "SmoothCast could not verify permission to use that receiver.",
    "source_unreachable": "The selected media source is not reachable.",
    "resource_exhausted": "No eligible node has enough capacity for this stream.",
    "format_unsupported": "No reachable node can play this stream on that receiver.",
    "invalid_request": "The casting request is invalid. Choose the source again.",
}


@dataclass(frozen=True)
class Request:
    target_id: str
    source_node_id: str
    source_kind: SourceKind
    codec: str
    current_session: str
    room_id: str


@dataclass(frozen=True)
class Capacity:
    node_id: str
    observed_age_ms: int
    codecs_direct: frozenset[str]
    codecs_remux: frozenset[str]
    codecs_transcode: frozenset[str]
    spare_streams: int
    link_measured: bool
    can_reach_source: bool
    lease_approved: bool
    rtt_ms: int


@dataclass(frozen=True)
class Plan:
    processing_node_id: str
    target_id: str
    mode: Mode
    source_node_id: str
    session_id: str
    requires_preflight: bool = True


@dataclass(frozen=True)
class NoRoute:
    code: str
    message: str


def _error(code: str) -> NoRoute:
    return NoRoute(code, _MESSAGES[code])


def _token(value: object) -> bool:
    return isinstance(value, str) and bool(_TOKEN.fullmatch(value))


def _valid(request: Request) -> bool:
    return (isinstance(request, Request)
            and all(_token(v) for v in (request.target_id, request.source_node_id,
                                       request.current_session, request.room_id))
            and request.source_kind in ("seekable_media", "live_mirror")
            and isinstance(request.codec, str) and bool(_CODEC.fullmatch(request.codec)))


def _valid_capacity(cap: Capacity) -> bool:
    if not isinstance(cap, Capacity) or not _token(cap.node_id):
        return False
    for value in (cap.observed_age_ms, cap.spare_streams, cap.rtt_ms):
        if type(value) is not int or value < 0 or value > 2**31:
            return False
    if any(type(v) is not bool for v in (cap.link_measured, cap.can_reach_source,
                                        cap.lease_approved)):
        return False
    for codecs in (cap.codecs_direct, cap.codecs_remux, cap.codecs_transcode):
        if not isinstance(codecs, frozenset) or len(codecs) > 64:
            return False
        if any(not isinstance(c, str) or not _CODEC.fullmatch(c) for c in codecs):
            return False
    return True


def _mode(req: Request, cap: Capacity) -> Mode | None:
    local = cap.node_id == req.source_node_id
    if req.source_kind == "live_mirror":
        # A live stream is not a seekable file and cannot use HTTP Range.
        return ("live_relay" if req.codec in cap.codecs_direct
                and (local or cap.link_measured) else None)
    if req.codec in cap.codecs_direct:
        return "direct" if local else "range_proxy"
    if req.codec in cap.codecs_remux:
        return "remux"
    if req.codec in cap.codecs_transcode and (local or cap.link_measured):
        return "transcode"
    return None


def select(request: Request, matrix: VisibilityMatrix,
           nodes: tuple[Capacity, ...], *, current: Plan | None = None) -> Plan | NoRoute:
    """Suggest a candidate, never command a target or assert playback readiness.

    All hints, including lease_approved, MUST be checked again by the owning
    playback controller before a stream starts.  No measured link means no
    offloaded encoder or remote live relay.
    """
    if (not _valid(request) or not isinstance(nodes, tuple) or len(nodes) > MAX_NODES
            or len(nodes) == 0 or any(not _valid_capacity(node) for node in nodes)
            or len({node.node_id for node in nodes}) != len(nodes)):
        return _error("invalid_request")
    entry = matrix.get(request.target_id)
    if entry is None:
        return _error("target_missing")
    routes = candidate_routes(matrix, request.target_id,
                              source_node=request.source_node_id)
    if not routes.candidates:
        if any(seen.state == "busy" for seen in entry.seen_by):
            return _error("target_busy")
        return _error("target_unreachable")
    capacities = {n.node_id: n for n in nodes}
    eligible: list[tuple[int, int, str, Plan]] = []
    reasons: set[str] = set()
    for candidate in routes.candidates[:MAX_NODES]:
        cap = capacities.get(candidate.node_id)
        if cap is None or cap.observed_age_ms > MAX_AGE_MS:
            reasons.add("target_unreachable")
            continue
        if not cap.lease_approved:
            reasons.add("lease_unverified")
            continue
        if not cap.can_reach_source:
            reasons.add("source_unreachable")
            continue
        if cap.spare_streams == 0:
            reasons.add("resource_exhausted")
            continue
        mode = _mode(request, cap)
        if mode is None:
            reasons.add("format_unsupported")
            continue
        plan = Plan(cap.node_id, request.target_id, mode,
                    request.source_node_id, request.current_session)
        eligible.append((_COST[mode], cap.rtt_ms, cap.node_id, plan))
    if not eligible:
        # Fail closed; an unverified lease outranks all optimisations.
        for code in ("lease_unverified", "source_unreachable", "resource_exhausted",
                     "format_unsupported", "target_unreachable"):
            if code in reasons:
                return _error(code)
        return _error("target_unreachable")
    if (isinstance(current, Plan) and current.requires_preflight
            and current.source_node_id == request.source_node_id
            and current.session_id == request.current_session):
        if any(plan == current for _cost, _rtt, _node, plan in eligible):
            return current
    return min(eligible, key=lambda item: item[:3])[3]
