"""Pure, deterministic streaming-route selection for browser-to-mesh media (#571).

The planner decides the *transfer path* for a browser-sourced media item: play
the original bytes straight through (browser Range, receiver Range, or a mesh
relay), re-encode (at the source or the destination), stream progressively while
the upload is still in flight, or require the whole file to arrive first.

This module is pure: no network, GTK, threads or filesystem. It is a pure
function of its inputs, so the same source/destination always yields the same
decision and the fallback ladder is auditable (and testable) without a device.

Why this differs from the codec-only capability matrix (#513): #513 answers "can
this receiver decode this codec?", one boolean per track. This module answers
"what is the lowest-latency *safe* path to get the bytes there?", which also
depends on Range support, throughput, buffering risk, public-address exposure
and whether the browser itself can play the file. A codec the receiver can
decode is useless if the bytes cannot reach it without a re-encode.

Route / fallback table (chosen when the row's condition holds; the ladder is
tried in order on failure)::

    condition                                   route                    fallback
    ------------------------------------------  -----------------------  -------------------------------------------
    codec ok, range ok, browser-direct allowed  direct_browser_range     receiver_range, mesh_relay, progressive, complete
    codec ok, range ok                          direct_receiver_range    mesh_relay, progressive, complete
    codec ok, no range, mesh relay              mesh_range_relay         progressive, complete
    codec ok, progressive-safe container        progressive_ingest       complete
    codec ok, otherwise                         must_complete_upload     -
    codec not ok, transcode at destination      transcode_at_destination complete
    codec not ok, transcode at source           transcode_at_source      transcode_at_destination, complete
    otherwise                                   must_complete_upload     -

Never returned: any ``direct_*``/``progressive_*`` route for an unplayable codec,
any route at all for an offline/refused source, and any route for a
public-address source unless the policy explicitly allows it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Route = Literal[
    "direct_browser_range",
    "direct_receiver_range",
    "mesh_range_relay",
    "transcode_at_source",
    "transcode_at_destination",
    "progressive_ingest",
    "must_complete_upload",
    "refuse",
]

MAX_TRACKS = 64
MAX_BUFFER_S = 3600.0
# Conservative cold-start defaults: assume a modest LAN link until a measurement
# (marked warm) says better.
COLD_THROUGHPUT_BPS = 8_000_000
MAX_BUFFER_INFLATION = 4.0

# Fixed, acyclic ladders. Every step is strictly further down the same order, so
# a fallback cannot loop back to a route already tried.
_FALLBACK: dict[str, tuple[str, ...]] = {
    "direct_browser_range": ("direct_receiver_range", "mesh_range_relay",
                             "progressive_ingest", "must_complete_upload"),
    "direct_receiver_range": ("mesh_range_relay", "progressive_ingest",
                              "must_complete_upload"),
    "mesh_range_relay": ("progressive_ingest", "must_complete_upload"),
    "transcode_at_destination": ("must_complete_upload",),
    "transcode_at_source": ("transcode_at_destination", "must_complete_upload"),
    "progressive_ingest": ("must_complete_upload",),
    "must_complete_upload": (),
    "refuse": (),
}


@dataclass(frozen=True)
class Source:
    """What the browser is offering: the file, its shape and its reachability."""

    online: bool
    public_address: bool
    container: str
    video_codec: str
    audio_codec: str
    size_bytes: int
    bitrate_bps: int
    faststart: bool
    range_supported: bool
    if_range_supported: bool


@dataclass(frozen=True)
class Capabilities:
    """Receiver/browser decode profile (#513) plus transfer capabilities here."""

    video_codecs: frozenset[str]
    audio_codecs: frozenset[str]
    containers: frozenset[str]
    range_supported: bool
    mse_supported: bool
    mesh_relay: bool
    can_transcode: bool


@dataclass(frozen=True)
class Destination:
    """The selected playback target as an observation, not a command."""

    reachable: bool
    browser_direct_allowed: bool
    can_transcode: bool


@dataclass(frozen=True)
class Measurements:
    """Bounded observations; ``warm`` gates whether throughput is trusted."""

    source_throughput_bps: int = 0
    target_throughput_bps: int = 0
    rtt_ms: int = 0
    transcode_throughput_bps: int = 0
    transcode_cpu_occupancy: float = 0.0
    disk_budget_bytes: int = 0
    warm: bool = False


@dataclass(frozen=True)
class Policy:
    """Owner policy and safety limits."""

    allow_transcode: bool = True
    allow_progressive: bool = True
    allow_public_address: bool = False
    min_startup_buffer_s: float = 4.0
    max_transcode_cpu: float = 0.9


@dataclass(frozen=True)
class Decision:
    route: Route
    reasons: tuple[str, ...]
    required_buffer_bytes: int
    fallback: tuple[Route, ...]


def _decision(route: Route, *reasons: str, buffer_bytes: int = 0) -> Decision:
    return Decision(route, tuple(reasons), buffer_bytes, _FALLBACK[route])


def _valid_tracks(codecs: object) -> bool:
    if not isinstance(codecs, frozenset) or len(codecs) > MAX_TRACKS:
        return False
    return all(isinstance(c, str) and c for c in codecs)


def _valid(source: object, destination: object, capabilities: object,
           measurements: object, policy: object) -> bool:
    if not isinstance(source, Source) or not isinstance(capabilities, Capabilities):
        return False
    if not isinstance(destination, Destination) or not isinstance(measurements, Measurements):
        return False
    if not isinstance(policy, Policy):
        return False
    for flag in (source.online, source.public_address, source.faststart,
                 source.range_supported, source.if_range_supported,
                 capabilities.range_supported, capabilities.mse_supported,
                 capabilities.mesh_relay, capabilities.can_transcode,
                 destination.reachable, destination.browser_direct_allowed,
                 destination.can_transcode, measurements.warm,
                 policy.allow_transcode, policy.allow_progressive,
                 policy.allow_public_address):
        if type(flag) is not bool:
            return False
    for text in (source.container, source.video_codec, source.audio_codec):
        if not isinstance(text, str) or not text or len(text) > 128:
            return False
    for count in (source.size_bytes, source.bitrate_bps, measurements.source_throughput_bps,
                  measurements.target_throughput_bps, measurements.rtt_ms,
                  measurements.transcode_throughput_bps, measurements.disk_budget_bytes):
        if type(count) is not int or count < 0:
            return False
    for cpu in (measurements.transcode_cpu_occupancy, policy.max_transcode_cpu):
        if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or not 0.0 <= cpu <= 1.0:
            return False
    buffer_s = policy.min_startup_buffer_s
    if (isinstance(buffer_s, bool) or not isinstance(buffer_s, (int, float))
            or not 0.0 < buffer_s <= MAX_BUFFER_S):
        return False
    return (_valid_tracks(capabilities.video_codecs)
            and _valid_tracks(capabilities.audio_codecs)
            and _valid_tracks(capabilities.containers))


def _playable(source: Source, capabilities: Capabilities) -> bool:
    """True only when the receiver can decode the source with no re-encode."""
    return (source.video_codec in capabilities.video_codecs
            and source.audio_codec in capabilities.audio_codecs
            and source.container in capabilities.containers)


def _progressive_safe(source: Source, policy: Policy) -> bool:
    """A faststart container can be played from the growing host file mid-upload.

    Progressive ingest reads the staged copy on the host, so it depends on the
    container being progressively decodable (moov before mdat), not on the
    browser offering HTTP Range.
    """
    return policy.allow_progressive and source.faststart


def _throughput_bps(measurements: Measurements) -> int:
    if measurements.warm and measurements.source_throughput_bps > 0:
        return measurements.source_throughput_bps
    return COLD_THROUGHPUT_BPS


def _required_buffer(source: Source, measurements: Measurements, policy: Policy) -> int:
    """Startup bytes: the bitrate over the budget, inflated when throughput lags."""
    if source.bitrate_bps <= 0:
        return 0
    throughput = _throughput_bps(measurements)
    inflation = 1.0
    if throughput < source.bitrate_bps:
        inflation = min(MAX_BUFFER_INFLATION, source.bitrate_bps / max(1, throughput))
    return int(source.bitrate_bps * policy.min_startup_buffer_s * inflation / 8.0)


def _can_transcode(destination: Destination, capabilities: Capabilities,
                   source: Source, measurements: Measurements, policy: Policy) -> bool:
    return (policy.allow_transcode
            and capabilities.can_transcode
            and measurements.transcode_cpu_occupancy <= policy.max_transcode_cpu
            and measurements.transcode_throughput_bps >= source.bitrate_bps)


def choose_stream_route(source: Source, destination: Destination,
                        capabilities: Capabilities, measurements: Measurements,
                        policy: Policy) -> Decision:
    """Return a reproducible route decision with reasons and a fallback ladder.

    The result is an observation, never a command: the owning playback
    controller still checks the lease, the receiver and the session before it
    starts anything. An unplayable codec is never claimed playable, and a
    public-address source is refused unless the policy allows it.
    """
    if not _valid(source, destination, capabilities, measurements, policy):
        return _decision("refuse", "invalid_input")
    if not source.online:
        return _decision("refuse", "source_offline")
    if source.public_address and not policy.allow_public_address:
        return _decision("refuse", "public_address_rejected")
    if not destination.reachable:
        return _decision("refuse", "destination_unreachable")

    reasons: list[str] = []
    if not source.if_range_supported:
        reasons.append("resume_unsupported")
    buffer_bytes = _required_buffer(source, measurements, policy)

    if _playable(source, capabilities):
        range_ok = source.range_supported and capabilities.range_supported
        if range_ok and destination.browser_direct_allowed and capabilities.mse_supported:
            return _decision("direct_browser_range", *reasons, "range_no_reencode",
                             buffer_bytes=buffer_bytes)
        if range_ok:
            return _decision("direct_receiver_range", *reasons, "range_no_reencode",
                             buffer_bytes=buffer_bytes)
        if capabilities.mesh_relay:
            return _decision("mesh_range_relay", *reasons, "mesh_relay_no_reencode",
                             buffer_bytes=buffer_bytes)
        if _progressive_safe(source, policy):
            return _decision("progressive_ingest", *reasons, "no_range_progressive",
                             buffer_bytes=buffer_bytes)
        return _decision("must_complete_upload", *reasons, "no_range_no_progressive",
                         buffer_bytes=buffer_bytes)
    if _can_transcode(destination, capabilities, source, measurements, policy):
        if destination.can_transcode:
            return _decision("transcode_at_destination", *reasons, "reencode_remote",
                             buffer_bytes=buffer_bytes)
        return _decision("transcode_at_source", *reasons, "reencode_local",
                         buffer_bytes=buffer_bytes)
    return _decision("must_complete_upload", *reasons, "codec_unsupported",
                     buffer_bytes=buffer_bytes)
