"""Pure, simulated route decisions (#564); no Chrome, GTK or device I/O."""
from __future__ import annotations

from dataclasses import replace
import ast
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_visibility import Seen, TargetEntry, candidate_routes, ready_observation_is_fresh
from mesh_cast_planner import Capacity, NoRoute, Plan, Request, select, MAX_NODES
from src import portal_target_picker


class Matrix:
    def __init__(self, *seen, target_id="tv"):
        self.target = TargetEntry(target_id, "TV", ("cast",), (), ("h264",),
                                  tuple(seen), seen[0].state if seen else "unreachable")

    def get(self, target_id):
        return self.target if self.target.id == target_id else None


def req(*, source_node="a", kind="seekable_media", codec="h264", session="s1"):
    return Request("tv", source_node, kind, codec, session, "room")


def cap(node="a", *, direct=("h264",), remux=(), transcode=(), **changes):
    return replace(Capacity(node, 0, frozenset(direct), frozenset(remux),
                            frozenset(transcode), 1, True, True, True, 2), **changes)


@pytest.mark.parametrize(("source_request", "capacities", "mode"), [
    (req(), (cap(),), "direct"),
    (req(), (cap("b"),), "range_proxy"),
    (req(codec="hevc"), (cap(remux=("hevc",)),), "remux"),
    (req(codec="av1"), (cap(transcode=("av1",)),), "transcode"),
    (req(kind="live_mirror"), (cap(),), "live_relay"),
    (req(codec="unknown"), (cap(),), None),
    (req(kind="live_mirror", source_node="a"),
     (cap("b", link_measured=False),), None),
])
def test_direct_proxy_remux_transcode_and_live_table(source_request, capacities, mode):
    matrix = Matrix(*(Seen(n.node_id, "ready", 0) for n in capacities))
    result = select(source_request, matrix, capacities)
    if mode is None:
        assert isinstance(result, NoRoute)
    else:
        assert isinstance(result, Plan) and result.mode == mode
        assert result.requires_preflight
        assert result.session_id == source_request.current_session


def test_busy_foreign_and_missing_lease_fail_closed():
    assert select(req(), Matrix(Seen("a", "busy", 0)), (cap(),)).code == "target_busy"
    assert select(req(), Matrix(Seen("a", "ready", 0)),
                  (cap(lease_approved=False),)).code == "lease_unverified"
    assert select(req(), Matrix(Seen("a", "ready", 0), Seen("b", "busy", 0)),
                  (cap("a", lease_approved=False), cap("b"))).code == "lease_unverified"


def test_stale_unreachable_and_exhausted_nodes_excluded():
    assert select(req(), Matrix(Seen("a", "stale", 0)), (cap(),)).code == "target_unreachable"
    assert select(req(), Matrix(Seen("a", "ready", 0)),
                  (cap(observed_age_ms=5001),)).code == "target_unreachable"
    assert select(req(), Matrix(Seen("a", "ready", 0)),
                  (cap(spare_streams=0),)).code == "resource_exhausted"
    assert select(req(), Matrix(Seen("a", "ready", 0)),
                  (cap(can_reach_source=False),)).code == "source_unreachable"
    assert select(req(), Matrix(Seen("a", "ready", 0)), (cap(),),
                  ).mode == "direct"
    assert select(req(), Matrix(Seen("a", "ready", 0)), (cap(),),
                  current=None).requires_preflight


def test_picker_and_planner_share_target_freshness_cutoff_and_recover_on_refresh():
    expired = Seen("fast", "ready", 15_001, 1)
    cutoff = Seen("fresh", "ready", 15_000, 40)
    assert ready_observation_is_fresh(cutoff)
    assert not ready_observation_is_fresh(expired)

    mixed = Matrix(expired, cutoff)
    assert [route.node_id for route in candidate_routes(mixed, "tv").candidates] == ["fresh"]
    picked = portal_target_picker.rows([mixed.target], ready_only=True)
    assert len(picked) == 1 and picked[0]["via"] == "fresh"
    plan = select(req(source_node="source"), mixed,
                  (cap("fast", rtt_ms=1), cap("fresh", rtt_ms=40)))
    assert isinstance(plan, Plan) and plan.processing_node_id == "fresh"

    all_expired = Matrix(Seen("fast", "ready", 15_001, 1),
                         Seen("fresh", "ready", 15_001, 40))
    unavailable = portal_target_picker.rows([all_expired.target], ready_only=True)
    assert unavailable == []
    assert select(req(source_node="source"), all_expired,
                  (cap("fast", rtt_ms=1), cap("fresh", rtt_ms=40))).code == "target_unreachable"

    refreshed = Matrix(Seen("fast", "ready", 0, 1), cutoff)
    assert portal_target_picker.rows([refreshed.target], ready_only=True)[0]["via"] == "fast"
    recovered = select(req(source_node="source"), refreshed,
                       (cap("fast", rtt_ms=1), cap("fresh", rtt_ms=40)))
    assert isinstance(recovered, Plan) and recovered.processing_node_id == "fast"


def test_unknown_link_does_not_claim_remote_offload():
    matrix = Matrix(Seen("b", "ready", 0))
    assert select(req(codec="av1"), matrix,
                  (cap("b", transcode=("av1",), link_measured=False),)).code == "format_unsupported"
    assert select(req(), matrix, (cap("b", link_measured=False),)).mode == "range_proxy"


def test_stable_node_ties_and_retain_current():
    matrix = Matrix(Seen("b", "ready", 0), Seen("c", "ready", 0))
    capacities = (cap("c", rtt_ms=1), cap("b", rtt_ms=3))
    best = select(req(), matrix, capacities)
    assert isinstance(best, Plan) and best.processing_node_id == "c"
    older = Plan("b", "tv", "range_proxy", "a", "s1")
    assert select(req(), matrix, capacities, current=older) == older
    # A previous sender/film cannot carry over its route during a new session.
    assert select(req(session="s2"), matrix, capacities, current=older) == replace(best, session_id="s2")
    assert select(req(), matrix, capacities,
                  current=replace(older, requires_preflight=False)) == best
    ties = (cap("b", rtt_ms=2), cap("c", rtt_ms=2))
    assert select(req(), matrix, ties).processing_node_id == "b"


def test_invalid_request_never_allocates_unbounded_candidates():
    matrix = Matrix(Seen("a", "ready", 0))
    for source_request, capacities in [
        (req(kind="something else"), (cap(),)),
        (req(codec=""), (cap(),)),
        (req(), tuple(cap(str(i)) for i in range(MAX_NODES+1))),
        (req(), (cap(), cap())),
        (req(), (cap(spare_streams=True),)),
        (req(), (cap(link_measured=1),)),
        (req(), (cap(direct=("x;hack",)),)),
    ]:
        assert select(source_request, matrix, capacities).code == "invalid_request"
    assert select(req(), matrix, (cap(),), current=None).mode == "direct"
    assert select(req(), Matrix(Seen("a", "ready", 0), target_id="other"),
                  (cap(),)).code == "target_missing"


def test_no_gui_network_or_receiver_side_effects_on_import():
    path = Path(__file__).resolve().parents[1] / "src/mesh_cast_planner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert set(imported) <= {"__future__", "dataclasses", "typing", "mesh_visibility"}
