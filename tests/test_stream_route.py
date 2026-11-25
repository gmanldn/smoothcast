"""Pure streaming-route planner contract (#571); no GUI, network or devices."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import stream_route
from stream_route import (Capabilities, Destination, Measurements, Policy, Source,
                          choose_stream_route)


def source(**kw):
    base = dict(online=True, public_address=False, container="mp4", video_codec="h264",
                audio_codec="aac", size_bytes=10_000_000, bitrate_bps=4_000_000,
                faststart=True, range_supported=True, if_range_supported=True)
    base.update(kw)
    return Source(**base)


def caps(**kw):
    base = dict(video_codecs=frozenset({"h264"}), audio_codecs=frozenset({"aac"}),
                containers=frozenset({"mp4"}), range_supported=True, mse_supported=True,
                mesh_relay=False, can_transcode=True)
    base.update(kw)
    return Capabilities(**base)


def dest(**kw):
    base = dict(reachable=True, browser_direct_allowed=True, can_transcode=False)
    base.update(kw)
    return Destination(**base)


def meas(**kw):
    base = dict(source_throughput_bps=0, target_throughput_bps=0, rtt_ms=0,
                transcode_throughput_bps=8_000_000, transcode_cpu_occupancy=0.0,
                disk_budget_bytes=0, warm=False)
    base.update(kw)
    return Measurements(**base)


def policy(**kw):
    base = dict(allow_transcode=True, allow_progressive=True, allow_public_address=False,
                min_startup_buffer_s=4.0, max_transcode_cpu=0.9)
    base.update(kw)
    return Policy(**base)


ROUTE_TABLE = [
    # (label, source, caps, dest, meas, policy, expected route)
    ("browser direct range", {}, {}, {}, {}, {}, "direct_browser_range"),
    ("receiver range when browser direct denied", {}, {},
     {"browser_direct_allowed": False}, {}, {}, "direct_receiver_range"),
    ("mesh relay without range", {"range_supported": False},
     {"range_supported": False, "mesh_relay": True}, {}, {}, {}, "mesh_range_relay"),
    ("progressive when no range or relay", {"range_supported": False},
     {"range_supported": False}, {}, {}, {}, "progressive_ingest"),
    ("complete upload when not progressive-safe",
     {"range_supported": False, "faststart": False}, {"range_supported": False}, {}, {}, {},
     "must_complete_upload"),
    ("transcode at destination", {"video_codec": "vp9"}, {},
     {"can_transcode": True}, {}, {}, "transcode_at_destination"),
    ("transcode at source", {"video_codec": "vp9"}, {"can_transcode": True},
     {"can_transcode": False}, {}, {"allow_transcode": True}, "transcode_at_source"),
    ("unsupported codec, no transcoder", {"video_codec": "vp9"},
     {"can_transcode": False}, {}, {}, {"allow_transcode": False}, "must_complete_upload"),
    ("offline source refuses", {"online": False}, {}, {}, {}, {}, "refuse"),
    ("public address refuses", {"public_address": True}, {}, {}, {}, {}, "refuse"),
    ("unreachable destination refuses", {}, {}, {"reachable": False}, {}, {}, "refuse"),
    ("public address allowed routes", {"public_address": True}, {}, {},
     {"warm": True}, {"allow_public_address": True}, "direct_browser_range"),
]


@pytest.mark.parametrize("label,src,cp,ds,me,po,expected", ROUTE_TABLE,
                         ids=[case[0] for case in ROUTE_TABLE])
def test_route_table(label, src, cp, ds, me, po, expected):
    decision = choose_stream_route(source(**src), dest(**ds), caps(**cp),
                                   meas(**me), policy(**po))
    assert decision.route == expected, label


def test_refusal_reasons_are_specific():
    assert choose_stream_route(source(online=False), dest(), caps(), meas(),
                               policy()).reasons == ("source_offline",)
    assert "public_address_rejected" in choose_stream_route(
        source(public_address=True), dest(), caps(), meas(), policy()).reasons
    assert "destination_unreachable" in choose_stream_route(
        source(), dest(reachable=False), caps(), meas(), policy()).reasons


def test_missing_if_range_is_reported_but_still_routes():
    decision = choose_stream_route(source(if_range_supported=False), dest(), caps(),
                                   meas(), policy())
    assert decision.route == "direct_browser_range"
    assert "resume_unsupported" in decision.reasons


def test_required_buffer_tracks_bitrate_and_throughput_deficit():
    small = choose_stream_route(source(bitrate_bps=1_000_000), dest(), caps(), meas(),
                                policy(min_startup_buffer_s=4.0))
    big = choose_stream_route(source(bitrate_bps=40_000_000), dest(), caps(), meas(),
                              policy(min_startup_buffer_s=4.0))
    assert small.required_buffer_bytes < big.required_buffer_bytes
    warm = choose_stream_route(source(), dest(), caps(),
                               meas(warm=True, source_throughput_bps=1_000_000), policy())
    assert warm.required_buffer_bytes > choose_stream_route(
        source(), dest(), caps(), meas(warm=True, source_throughput_bps=100_000_000),
        policy()).required_buffer_bytes


def test_invalid_inputs_refuse_and_never_raise():
    for bad in (None, object(), "mp4", 5):
        assert choose_stream_route(bad, dest(), caps(), meas(), policy()).route == "refuse"
    assert choose_stream_route(source(container=""), dest(), caps(), meas(),
                               policy()).route == "refuse"
    assert choose_stream_route(source(size_bytes=-1), dest(), caps(), meas(),
                               policy()).route == "refuse"
    assert choose_stream_route(source(), dest(), caps(), meas(),
                               policy(min_startup_buffer_s=0.0)).route == "refuse"
    assert choose_stream_route(source(), dest(), caps(), meas(),
                               policy(max_transcode_cpu=2.0)).route == "refuse"
    assert choose_stream_route(source(), dest(),
                               caps(video_codecs=frozenset({7})), meas(),
                               policy()).route == "refuse"


def test_unplayable_codec_is_never_claimed_direct():
    """Property: an undecodable codec never yields a no-re-encode route."""
    for codec in ("vp9", "av1", "mpeg2"):
        decision = choose_stream_route(source(video_codec=codec), dest(), caps(), meas(),
                                       policy())
        assert decision.route not in {"direct_browser_range", "direct_receiver_range",
                                      "mesh_range_relay", "progressive_ingest"}


def test_fallback_ladders_are_acyclic_and_terminate():
    """Property: no route is reachable from its own ladder, so it terminates."""
    for start in stream_route._FALLBACK:
        stack = list(stream_route._FALLBACK[start])
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            assert current != start, f"{start} is reachable from its own ladder"
            if current in visited:
                continue
            visited.add(current)
            stack.extend(stream_route._FALLBACK[current])


def test_decisions_are_deterministic_across_the_decision_space():
    """Property: identical inputs always produce identical decisions."""
    for src in ({}, {"range_supported": False}, {"public_address": True}):
        for cp in ({}, {"mesh_relay": True}, {"can_transcode": False}):
            for allowed in (False, True):
                args = (source(**src), dest(), caps(**cp), meas(warm=True),
                        policy(allow_public_address=allowed))
                assert choose_stream_route(*args) == choose_stream_route(*args)


def test_public_address_never_routes_without_explicit_opt_in():
    """Property: no direct/relay/progressive route escapes a public source."""
    for cp in ({}, {"mesh_relay": True}):
        decision = choose_stream_route(source(public_address=True), dest(), caps(**cp),
                                       meas(), policy(allow_public_address=False))
        assert decision.route == "refuse"


def test_forty_eight_media_shapes_across_three_mesh_topologies():
    """Broad cross-product: every shape routes validly and reproducibly."""
    codecs = ["h264", "vp9", "hevc", "av1"]
    containers = ["mp4", "mkv", "webm"]
    shapes = [{"video_codec": c, "container": k, "faststart": f, "range_supported": r}
              for c in codecs for k in containers for f in (True, False) for r in (True, False)]
    assert len(shapes) == 48
    topologies = [
        ({"browser_direct_allowed": True}, {}),                       # browser-direct
        ({"browser_direct_allowed": False}, {"mesh_relay": True}),    # mesh relay
        ({"browser_direct_allowed": False}, {}),                      # receiver only
    ]
    produced = set()
    for shape in shapes:
        for dest_kw, cap_kw in topologies:
            for warm in (False, True):
                args = (source(**shape), dest(**dest_kw), caps(**cap_kw),
                        meas(warm=warm), policy())
                decision = choose_stream_route(*args)
                assert decision.route in stream_route._FALLBACK
                assert decision == choose_stream_route(*args)
                produced.add(decision.route)
    assert len(produced) >= 5


def test_planner_is_fast_and_gtk_free():
    """Perf contract: under 2 ms per decision, with no GUI or network imports."""
    arguments = (source(), dest(), caps(), meas(warm=True), policy())
    start = time.perf_counter()
    for _ in range(2000):
        choose_stream_route(*arguments)
    assert (time.perf_counter() - start) / 2000 < 0.002
    assert "gi" not in sys.modules


def test_every_route_is_reachable_in_a_small_decision_space():
    """Every contract route (bar refuse) is producible by some input."""
    produced = set()
    for cp in ({}, {"mesh_relay": True}, {"can_transcode": False}, {"range_supported": False}):
        for src in ({}, {"range_supported": False}, {"faststart": False}, {"video_codec": "vp9"}):
            for ds in ({}, {"browser_direct_allowed": False}, {"can_transcode": True}):
                decision = choose_stream_route(source(**src), dest(**ds), caps(**cp),
                                               meas(warm=True), policy())
                produced.add(decision.route)
    assert {"direct_browser_range", "direct_receiver_range", "mesh_range_relay",
            "transcode_at_source", "transcode_at_destination", "progressive_ingest",
            "must_complete_upload"} <= produced


def test_ladder_steps_are_the_documented_ones():
    assert choose_stream_route(source(), dest(), caps(), meas(), policy()).fallback == (
        "direct_receiver_range", "mesh_range_relay", "progressive_ingest",
        "must_complete_upload")
    assert choose_stream_route(source(online=False), dest(), caps(), meas(),
                               policy()).fallback == ()
