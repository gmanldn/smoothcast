"""Mesh wire model: round trips, caps, tiers, strict parsing (ticket #394)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_model as mm

NODE = "a" * 32
OTHER = "b" * 32
BOOT = "c" * 32


def target(index=0, **kw):
    base = dict(id=f"uuid-{index:03d}", kind="cast", name=f"TV {index}")
    base.update(kw)
    return mm.TargetObservation(**base)


def record(**kw):
    base = dict(node_id=NODE, boot_id=BOOT, name="Lounge PC", version="1.2.0",
                incarnation=2, rev=7, boot_epoch=1_700_000_000,
                capabilities=("room", "screens"), mesh_port=8801, room_port=8800,
                addresses=("192.168.1.20",))
    base.update(kw)
    return mm.NodeRecord(**base)


def full():
    return record(
        targets=(target(2, model="Chromecast", formats=("video/mp4", "audio/mpeg"),
                        state="busy", age_ms=1200, owner=OTHER), target(1)),
        clients=(mm.ClientSummary("c1", "screen", ("video",), 30, "Kitchen TV"),
                 mm.ClientSummary("c0", "controller")),
        sources=(mm.SourceSummary("audio", 120, ("audio/flac",)),),
        edges=(mm.EdgeObservation("node", OTHER, 500, 3),
               mm.EdgeObservation("target", "uuid-001", None, None, "timeout")),
    )


# -- round trip and canonical form -----------------------------------------

def test_record_round_trips_through_canonical_bytes():
    original = full()
    decoded = mm.parse_record_bytes(mm.encode_record(original))
    assert decoded == mm.parse_record(original.to_wire())
    assert decoded.targets[0].id == "uuid-001"          # sorted canonically
    assert mm.encode_record(decoded) == mm.encode_record(original)


def test_digest_is_order_independent_and_changes_with_content():
    a = full()
    shuffled = record(
        targets=tuple(reversed(a.targets)), clients=tuple(reversed(a.clients)),
        sources=a.sources, edges=tuple(reversed(a.edges)))
    assert mm.record_digest(a) == mm.record_digest(shuffled)
    assert mm.record_digest(a) != mm.record_digest(record(rev=8))
    assert len(mm.record_digest(a)) == 64


def test_encoding_is_ascii_stable_and_handles_unicode_names():
    rec = record(name="Wohnzimmer – Büro 🎬")
    raw = mm.encode_record(rec)
    assert raw.isascii() and b": " not in raw and b", " not in raw
    assert mm.parse_record_bytes(raw).name == rec.name
    assert raw == mm.encode_record(mm.parse_record_bytes(raw))


def test_digest_summaries_and_hash():
    digest = mm.digest_of([record(), record(node_id=OTHER, rev=3)])
    assert digest[NODE] == (BOOT, 7)
    assert mm.parse_digest(json.loads(json.dumps(digest))) == digest
    assert mm.digest_hash(digest) == mm.digest_hash(dict(reversed(list(digest.items()))))
    assert mm.digest_hash(digest) != mm.digest_hash({NODE: (BOOT, 8)})


@pytest.mark.parametrize("bad", [
    [], {NODE: [BOOT]}, {NODE: [BOOT, True]}, {NODE: [BOOT, -1]},
    {"short": [BOOT, 1]}, {NODE: ["x", 1]}, {NODE: [BOOT, 1.5]},
    {("%032x" % i): [BOOT, 1] for i in range(mm.MAX_NODES + 1)},
])
def test_bad_digests_are_rejected(bad):
    with pytest.raises(mm.MeshModelError):
        mm.parse_digest(bad)


# -- strict validation -----------------------------------------------------

def mutated(**changes):
    wire = full().to_wire()
    wire.update(changes)
    return wire


@pytest.mark.parametrize("changes", [
    {"v": 2}, {"v": True}, {"v": "1"}, {"v": 0},
    {"node_id": "A" * 32}, {"node_id": "a" * 31}, {"boot_id": None},
    {"name": ""}, {"name": " padded "}, {"name": "x" * (mm.MAX_NAME + 1)},
    {"name": "bell\x07"}, {"name": "line\nbreak"}, {"name": "sep "},
    {"version": "1.2"}, {"version": "v1.2.0"},
    {"incarnation": -1}, {"incarnation": 2.0}, {"incarnation": True},
    {"rev": 2 ** 60}, {"boot_epoch": float("nan")},
    {"protocols": []}, {"protocols": ["1"]}, {"protocols": list(range(1, 20))},
    {"capabilities": ["Room"]}, {"capabilities": ["room", "room"]},
    {"capabilities": ["x" * 40]}, {"capabilities": "room"},
    {"status": "sleeping"}, {"mesh_port": 0}, {"room_port": 70000},
    {"mesh_port": "8801"},
    {"addresses": ["8.8.8.8"]}, {"addresses": ["::1"]}, {"addresses": ["example.com"]},
    {"addresses": ["192.168.1.2", "192.168.1.2"]},
    {"addresses": ["10.0.0.%d" % i for i in range(mm.MAX_ADDRESSES + 1)]},
    {"truncated": 1}, {"targets": "x"}, {"clients": {}}, {"edges": None},
])
def test_invalid_fields_are_rejected(changes):
    with pytest.raises(mm.MeshModelError):
        mm.parse_record(mutated(**changes))


@pytest.mark.parametrize("path,value", [
    (("targets", 0, "kind"), "airplay"), (("targets", 0, "state"), "on-fire"),
    (("targets", 0, "id"), "../x"), (("targets", 0, "id"), ""),
    (("targets", 0, "age_ms"), -1), (("targets", 0, "age_ms"), 10 ** 12),
    (("targets", 0, "owner"), "nope"), (("targets", 0, "formats"), ["BAD"]),
    (("clients", 0, "role"), "admin"), (("clients", 0, "id"), "has space"),
    (("clients", 0, "flags"), ["a"] * 3), (("clients", 0, "age_s"), 2.5),
    (("sources", 0, "kind"), "books"), (("sources", 0, "count"), -3),
    (("sources", 0, "count"), 10 ** 9),
    (("edges", 0, "peer_kind"), "router"), (("edges", 0, "peer"), "x"),
    (("edges", 0, "reason"), "cosmic-rays"), (("edges", 0, "rtt_ms"), -5),
    (("edges", 1, "peer"), "../../etc"),
])
def test_invalid_nested_fields_are_rejected(path, value):
    wire = full().to_wire()
    node = wire
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    with pytest.raises(mm.MeshModelError):
        mm.parse_record(wire)


def test_duplicate_entries_are_rejected():
    wire = full().to_wire()
    wire["targets"].append(dict(wire["targets"][0]))
    with pytest.raises(mm.MeshModelError):
        mm.parse_record(wire)
    wire = full().to_wire()
    wire["clients"].append(dict(wire["clients"][0]))
    with pytest.raises(mm.MeshModelError):
        mm.parse_record(wire)


def test_unknown_fields_are_ignored_for_forward_compatibility():
    wire = full().to_wire()
    wire["future_feature"] = {"x": 1}
    wire["targets"][0]["colour"] = "red"
    assert mm.parse_record(wire) == mm.parse_record(full().to_wire())


def test_raw_message_hazards_are_rejected_before_parsing():
    good = mm.encode_record(full())
    for bad in (b"", b"{", b"[]", b"null", b'{"v":1,"v":1}', b"\xff\xfe",
                b'{"v":NaN}', b'{"v":Infinity}', good + b" " * mm.MAX_RECORD_BYTES,
                "x" * (mm.MAX_RECORD_BYTES + 1), 7, None, [1]):
        with pytest.raises(mm.MeshModelError):
            mm.parse_record_bytes(bad)
    deep = b"[" * 5000 + b"]" * 5000
    with pytest.raises(mm.MeshModelError):
        mm.parse_record_bytes(deep)
    assert mm.parse_record_bytes(good.decode()) == mm.parse_record(full().to_wire())
    assert mm.parse_record_bytes(bytearray(good)).node_id == NODE


# -- caps and overflow -----------------------------------------------------

def test_list_caps_are_enforced_on_parse():
    wire = record().to_wire()
    wire["targets"] = [target(i).to_wire() for i in range(mm.MAX_TARGETS + 1)]
    with pytest.raises(mm.MeshModelError):
        mm.parse_record(wire)
    wire["targets"] = [target(i).to_wire() for i in range(mm.MAX_TARGETS)]
    assert len(mm.parse_record(wire).targets) == mm.MAX_TARGETS


def test_encoding_refuses_an_oversized_record_and_fit_shrinks_it():
    big = record(
        targets=tuple(target(i, name="N" * 40, model="M" * 60,
                             formats=tuple(f"video/x-{j}" for j in range(15)))
                      for i in range(60)),
        clients=tuple(mm.ClientSummary(f"c{i}", "screen", name="n" * 40)
                      for i in range(60)),
        edges=tuple(mm.EdgeObservation("target", f"uuid-{i:03d}", i, 5)
                    for i in range(100)))
    assert mm.encoded_size(big) > mm.MAX_RECORD_BYTES
    with pytest.raises(mm.MeshModelError):
        mm.encode_record(big)
    fitted = mm.fit_record(big)
    assert fitted.truncated and mm.encoded_size(fitted) <= mm.MAX_RECORD_BYTES
    assert (fitted.node_id, fitted.boot_id, fitted.rev) == (NODE, BOOT, 7)
    assert mm.parse_record_bytes(mm.encode_record(fitted)) is not None


def test_fit_keeps_the_most_valuable_entries():
    targets = tuple(target(i, state="unreachable" if i < 40 else "ready")
                    for i in range(mm.MAX_TARGETS + 10))
    fitted = mm.fit_record(record(targets=targets))
    assert len(fitted.targets) == mm.MAX_TARGETS and fitted.truncated
    assert all(t.state == "ready" for t in fitted.targets if int(t.id[-3:]) >= 40)
    assert sum(t.state == "ready" for t in fitted.targets) == 34  # all ready kept


def test_fit_leaves_small_records_alone_and_is_idempotent():
    small = full()
    assert mm.fit_record(small) == small and not small.truncated
    big = record(edges=tuple(mm.EdgeObservation("target", f"t{i:03d}", i)
                             for i in range(mm.MAX_EDGES + 5)))
    once = mm.fit_record(big)
    assert mm.fit_record(once) == once


def test_fit_fails_only_when_identity_alone_cannot_fit():
    with pytest.raises(mm.MeshModelError):
        mm.fit_record(record(), limit=50)


def test_mesh_limits_refuse_the_newest_unknown_node():
    existing = {f"{i:032x}": record(node_id=f"{i:032x}") for i in range(mm.MAX_NODES)}
    newcomer = record(node_id="f" * 32)
    assert mm.would_exceed_mesh_limits(existing, newcomer)
    replacement = record(node_id=f"{0:032x}", rev=99)
    assert not mm.would_exceed_mesh_limits(existing, replacement)
    assert mm.mesh_size(existing.values()) > 0


def test_mesh_total_size_cap():
    heavy = record(targets=tuple(target(i, name="N" * 40, model="M" * 60,
                                        formats=("video/mp4", "audio/mpeg"))
                                 for i in range(60)))
    size = mm.encoded_size(heavy)
    count = mm.MAX_MESH_BYTES // size
    existing = {f"{i:032x}": record(node_id=f"{i:032x}", targets=heavy.targets)
                for i in range(count)}
    assert mm.would_exceed_mesh_limits(existing, record(node_id="e" * 32,
                                                        targets=heavy.targets))


# -- protocol negotiation --------------------------------------------------

def test_protocol_negotiation():
    assert mm.negotiate_protocol([1, 2], [2, 3]) == 2
    assert mm.negotiate_protocol((1,), [1]) == 1
    for local, remote in (([1], [2]), ([], [1]), ([1], []), ([1], ["x"]), ([1], [None]),
                          ([1], [0, -1]), ([1], [True]), ([1], [1.0]),
                          ([1], ["1"]), ([1], range(1, 100)),
                          ([1], [1] * (mm.MAX_PROTOCOLS + 1)))):
        with pytest.raises(mm.MeshModelError):
            mm.negotiate_protocol(local, remote)


# -- tiers -----------------------------------------------------------------

SECRETS = ("Secret Kitchen TV", "Sam's phone", "SecretModel", "uuid-secret",
           "10.9.8.7", "audio/secret-codec")


def secret_record():
    return record(
        addresses=("10.9.8.7",),
        targets=(mm.TargetObservation("uuid-secret", "cast", "Secret Kitchen TV",
                                      model="SecretModel"),),
        clients=(mm.ClientSummary("cl1", "screen", name="Sam's phone"),),
        sources=(mm.SourceSummary("audio", 5, ("audio/secret-codec",)),),
        edges=(mm.EdgeObservation("target", "uuid-secret", 1, 1),))


def test_public_tier_is_identity_only():
    wire = mm.public_tier(secret_record())
    text = json.dumps(wire)
    for secret in SECRETS:
        assert secret not in text
    assert set(wire) == {"v", "node_id", "boot_id", "incarnation", "rev",
                         "boot_epoch", "name", "version", "protocols",
                         "capabilities", "status", "mesh_port", "room_port"}
    assert wire["capabilities"] == ["room", "screens"]


def test_guest_tier_shows_targets_but_no_clients_edges_sources_or_addresses():
    wire = mm.guest_tier(secret_record())
    text = json.dumps(wire)
    assert "Secret Kitchen TV" in text and wire["client_count"] == 1
    for secret in ("Sam's phone", "10.9.8.7", "audio/secret-codec"):
        assert secret not in text
    assert "edges" not in wire and "clients" not in wire and "sources" not in wire


def test_full_tier_is_the_whole_record_and_reparses():
    rec = secret_record()
    assert mm.parse_record(mm.full_tier(rec)) == rec


# -- builder helpers -------------------------------------------------------

def test_clean_text_and_address_helpers():
    assert mm.clean_text("  A\x00 b\n\tc  ", 10) == "A b c"
    assert mm.clean_text("x" * 100, 5) == "xxxxx"
    assert mm.clean_text(None, 5, fallback="Screen") == "Screen"
    assert mm.clean_text("\x00\x01", 5, fallback="?") == "?"
    for ok in ("10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.0.9",
               "169.254.3.4", "127.0.0.1"):
        assert mm.is_lan_address(ok)
    for bad in ("172.32.0.1", "8.8.8.8", "1.2.3", "::1", "", None, 5, "192.168.1.1/24",
                "0x7f.0.0.1", "192.168.001.001"):
        assert not mm.is_lan_address(bad)


# -- fuzzing (hypothesis, seeded like tests/test_fuzz_parsers.py) ------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

FUZZ = settings(max_examples=200, deadline=None, derandomize=True,
                suppress_health_check=[HealthCheck.too_slow])

JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True)
    | st.text(max_size=40),
    lambda inner: st.lists(inner, max_size=5)
    | st.dictionaries(st.text(max_size=10), inner, max_size=6),
    max_leaves=30)

hex32 = st.text("0123456789abcdef", min_size=32, max_size=32)
safe_text = st.text(
    st.characters(blacklist_categories=("C", "Zl", "Zp")), min_size=1, max_size=20
).filter(lambda t: t == t.strip())
token = st.from_regex(r"[a-z0-9][a-z0-9-]{0,10}", fullmatch=True)
fmt = st.from_regex(r"[a-z0-9][a-z0-9/.+-]{0,20}", fullmatch=True)
tid = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,20}", fullmatch=True)

targets = st.lists(st.builds(
    mm.TargetObservation, id=tid, kind=st.sampled_from(sorted(mm.TARGET_KINDS)),
    name=safe_text, state=st.sampled_from(sorted(mm.TARGET_STATES)),
    model=st.just("") | safe_text, formats=st.lists(fmt, max_size=4, unique=True).map(tuple),
    age_ms=st.integers(0, 10 ** 6), owner=st.just("") | hex32),
    max_size=8, unique_by=lambda t: t.id).map(tuple)
clients = st.lists(st.builds(
    mm.ClientSummary, id=st.from_regex(r"[A-Za-z0-9_-]{1,10}", fullmatch=True),
    role=st.sampled_from(sorted(mm.CLIENT_ROLES)), flags=st.just(()),
    age_s=st.integers(0, 10 ** 5), name=st.just("") | safe_text),
    max_size=8, unique_by=lambda c: c.id).map(tuple)
edges = st.lists(st.builds(
    mm.EdgeObservation, peer_kind=st.just("target"), peer=tid,
    last_ok_ms=st.none() | st.integers(0, 10 ** 6),
    rtt_ms=st.none() | st.integers(0, 10 ** 4),
    reason=st.sampled_from(sorted(mm.EDGE_REASONS))),
    max_size=8, unique_by=lambda e: e.peer).map(tuple)
records = st.builds(
    mm.NodeRecord, node_id=hex32, boot_id=hex32, name=safe_text,
    version=st.just("1.2.3"), incarnation=st.integers(0, 10 ** 6),
    rev=st.integers(0, 10 ** 9), boot_epoch=st.integers(0, 2 ** 33),
    capabilities=st.lists(token, max_size=5, unique=True).map(tuple),
    status=st.sampled_from(sorted(mm.NODE_STATUSES)),
    mesh_port=st.none() | st.integers(1, 65535), room_port=st.none() | st.integers(1, 65535),
    addresses=st.lists(st.sampled_from(["10.0.0.1", "192.168.1.5", "172.16.9.9"]),
                       max_size=3, unique=True).map(tuple),
    targets=targets, clients=clients, edges=edges)


@FUZZ
@given(JSON)
def test_arbitrary_json_only_raises_the_model_error(value):
    try:
        parsed = mm.parse_record(value)
    except mm.MeshModelError:
        return
    assert mm.encoded_size(parsed) <= 4 * mm.MAX_RECORD_BYTES


@FUZZ
@given(st.binary(max_size=2048))
def test_arbitrary_bytes_only_raise_the_model_error(blob):
    try:
        mm.parse_record_bytes(blob)
    except mm.MeshModelError:
        pass


@FUZZ
@given(JSON)
def test_arbitrary_digests_only_raise_the_model_error(value):
    try:
        mm.parse_digest(value)
    except mm.MeshModelError:
        pass


@FUZZ
@given(records)
def test_every_valid_record_round_trips_and_digests_stably(rec):
    fitted = mm.fit_record(rec)
    raw = mm.encode_record(fitted)
    again = mm.parse_record_bytes(raw)
    assert again == mm.parse_record(fitted.to_wire())
    assert mm.encode_record(again) == raw
    assert mm.record_digest(again) == mm.record_digest(fitted)
    assert len(raw) <= mm.MAX_RECORD_BYTES


@FUZZ
@given(records)
def test_public_and_guest_tiers_expose_only_their_allow_list(rec):
    public = mm.public_tier(rec)
    assert set(public) == {
        "v", "node_id", "boot_id", "incarnation", "rev", "boot_epoch", "name",
        "version", "protocols", "capabilities", "status", "mesh_port", "room_port"}
    guest = mm.guest_tier(rec)
    assert not {"clients", "edges", "sources", "addresses"} & set(guest)
    assert guest["client_count"] == len(rec.clients)
    assert set(guest) - set(public) == {"targets", "client_count"}
