"""Pure, simulated route decisions (#564); no Chrome, GTK or device I/O."""
from __future__ import annotations

from dataclasses import replace
import ast
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_visibility import Seen, TargetEntry
from mesh_cast_planner import Capacity, NoRoute, Plan, Request, select, MAX_NODES


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
    matrix = Matrix(*(Seen(n.node_id, "ready") for n in capacities))
    result = select(source_request, matrix, capacities)
    if mode is None:
        assert isinstance(result, NoRoute)
    else:
        assert isinstance(result, Plan) and result.mode == mode
        assert result.requires_preflight
        assert result.session_id == source_request.current_session


def test_busy_foreign_and_missing_lease_fail_closed():
    assert select(req(), Matrix(Seen("a", "busy")), (cap(),)).code == "target_busy"
    assert select(req(), Matrix(Seen("a", "ready")),
                  (cap(lease_approved=False),)).code == "lease_unverified"
    assert select(req(), Matrix(Seen("a", "ready"), Seen("b", "busy")),
                  (cap("a", lease_approved=False), cap("b"))).code == "lease_unverified"


def test_stale_unreachable_and_exhausted_nodes_excluded():
    assert select(req(), Matrix(Seen("a", "stale")), (cap(),)).code == "target_unreachable"
    assert select(req(), Matrix(Seen("a", "ready")),
                  (cap(observed_age_ms=5001),)).code == "target_unreachable"
    assert select(req(), Matrix(Seen("a", "ready")),
                  (cap(spare_streams=0),)).code == "resource_exhausted"
    assert select(req(), Matrix(Seen("a", "ready")),
                  (cap(can_reach_source=False),)).code == "source_unreachable"
    assert select(req(), Matrix(Seen("a", "ready")), (cap(),),
                  ).mode == "direct"
    assert select(req(), Matrix(Seen("a", "ready")), (cap(),),
                  current=None).requires_preflight


def test_unknown_link_does_not_claim_remote_offload():
    matrix = Matrix(Seen("b", "ready"))
    assert select(req(codec="av1"), matrix,
                  (cap("b", transcode=("av1",), link_measured=False),)).code == "format_unsupported"
    assert select(req(), matrix, (cap("b", link_measured=False),)).mode == "range_proxy"


def test_stable_node_ties_and_retain_current():
    matrix = Matrix(Seen("b", "ready"), Seen("c", "ready"))
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
    matrix = Matrix(Seen("a", "ready"))
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
    assert select(req(), Matrix(Seen("a", "ready"), target_id="other"),
                  (cap(),)).code == "target_missing"


def test_no_gui_network_or_receiver_side_effects_on_import():
    path = Path(__file__).resolve().parents[1] / "src/mesh_cast_planner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert set(imported) <= {"__future__", "dataclasses", "typing", "mesh_visibility"}
