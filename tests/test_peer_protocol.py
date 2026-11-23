"""#387: golden peer messages, negotiation matrix, malformed inputs and downgrade safety."""
from __future__ import annotations

import itertools
import json

import pytest

from peer_protocol import (
    PeerCompatibilityError, Handshake, parse_handshake, local_handshake,
    legacy_handshake, negotiate, parse_store, MAX_HANDSHAKE_BYTES,
)

GOLDEN_V1 = b'{"app_version":"1.0.0","caps":["mesh.records.v1"],"min_proto":1,"proto":1}'


def test_golden_v1_decode_and_encode():
    msg = parse_handshake(json.loads(GOLDEN_V1))
    assert msg == Handshake(1, 1, "1.0.0", ("mesh.records.v1",))
    assert json.dumps(msg.wire(), sort_keys=True, separators=(",", ":")).encode() == GOLDEN_V1


def test_capability_intersection_matrix_and_per_peer_kill_switch():
    caps = ("mesh.records.v1", "resume.v1", "catalogue.v1")
    subsets = [pair for n in range(4) for pair in itertools.combinations(caps, n)]
    for left, right in itertools.product(subsets, repeat=2):
        ours, theirs = local_handshake("1.2.15", left), local_handshake("1.2.14", right)
        assert negotiate(ours, theirs).caps == set(left) & set(right)
        assert negotiate(ours, theirs, disabled=frozenset({"resume.v1"})).caps == (
            (set(left) & set(right)) - {"resume.v1"}
        )
    assert not negotiate(local_handshake("1.2.15"), legacy_handshake(), legacy=True).caps


def test_incompatible_proto_fails_before_any_capability_is_enabled():
    ours = local_handshake("1.2.15")
    for proto, minimum in ((2, 2), (100, 50), (65535, 3)):
        with pytest.raises(PeerCompatibilityError, match="Incompatible"):
            negotiate(ours, Handshake(proto, minimum, "9.9.9", ("mesh.records.v1",)))


@pytest.mark.parametrize("bad", [
    {}, [], None, {"proto": True, "min_proto": 1, "app_version": "1.0.0", "caps": []},
    {"proto": 2, "min_proto": 3, "app_version": "1.0.0", "caps": []},
    {"proto": 1, "min_proto": 1, "app_version": "v1.0.0", "caps": []},
    {"proto": 1, "min_proto": 1, "app_version": "1.0.0", "caps": ["a", "a"]},
    {"proto": 1, "min_proto": 1, "app_version": "1.0.0", "caps": ["../x"]},
    {"proto": 1, "min_proto": 1, "app_version": "1.0.0", "caps": ["a"] * 33},
    {"proto": 1, "min_proto": 1, "app_version": "1.0.0",
     "caps": [], "future": "x" * MAX_HANDSHAKE_BYTES},
])
def test_handshake_fails_closed_and_bounded(bad):
    with pytest.raises(PeerCompatibilityError):
        parse_handshake(bad)


def test_optional_future_fields_ignored_and_never_enable_capabilities():
    raw = local_handshake("1.2.15").wire()
    raw["future_capabilities"] = ["resume.v1"]
    assert parse_handshake(raw).caps == ("mesh.records.v1",)


def test_unknown_store_fields_survive_round_trip_and_updates():
    original = {"schema": 1, "watched": True, "future": {"lang": "en", "data": [1, 2]}}
    document = parse_store(original)
    original["future"]["data"].append(3)
    assert document.update({"watched": False}).wire() == {
        "schema": 1, "watched": False, "future": {"lang": "en", "data": [1, 2]},
    }


def test_newer_schema_is_read_only_on_downgrade():
    document = parse_store({"schema": 5, "future": "keep"}, supported_schema=1)
    assert document.read_only
    assert document.wire() == {"schema": 5, "future": "keep"}
    with pytest.raises(PeerCompatibilityError):
        document.update({"future": "drop"})
    with pytest.raises(PeerCompatibilityError):
        parse_store({"schema": True})
    with pytest.raises(PeerCompatibilityError):
        parse_store({"schema": 1, "future": "X" * (128 * 1024)})
