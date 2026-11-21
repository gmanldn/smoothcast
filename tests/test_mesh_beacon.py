"""Presence beacon: codec, abuse protection and simulated join/leave budgets (#396)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_beacon as mb
import mesh_sim as ms
from mesh_beacon_node import BeaconNode
from mesh_ports import Datagram

A, B, C = "a" * 32, "b" * 32, "c" * 32


def msg(kind="heartbeat", node=A, boot=B, **kw):
    base = dict(kind=kind, node_id=node, boot_id=boot, incarnation=1, rev=3,
                boot_epoch=1_700_000_000, port=8801, nonce="0123456789abcdef")
    base.update(kw)
    return mb.Message(**base)


# -- codec -------------------------------------------------------------------

def test_round_trip_and_size_limit():
    full = msg("welcome", echo="f" * 16,
               hints=tuple((f"192.168.1.{i}", 8801) for i in range(mb.MAX_HINTS)))
    data = mb.encode(full)
    assert len(data) <= mb.MAX_DATAGRAM and mb.decode(data) == full
    assert len(mb.encode(msg())) < 260                       # heartbeats stay tiny


@pytest.mark.parametrize("raw", [
    b"", b"{", b"[]", b"null", b"\xff", b"x" * 600, b'{"k":"B"}',
    b'{"k":"Z","v":1}', b'{"k":"B","v":2}', b'{"k":"B","v":true}',
])
def test_garbage_is_rejected(raw):
    with pytest.raises(mb.BeaconError):
        mb.decode(raw)


@pytest.mark.parametrize("field,value", [
    ("n", "short"), ("b", None), ("x", "zz"), ("i", -1), ("i", 1.5), ("i", True),
    ("r", 2 ** 60), ("e", "now"), ("p", 0), ("p", 70000), ("y", "bad"),
    ("h", [["8.8.8.8", 1]]), ("h", [["192.168.1.2"]]), ("h", "x"),
    ("h", [["192.168.1.2", 1]] * (mb.MAX_HINTS + 1)), ("h", [["192.168.1.2", 0]]),
])
def test_bad_fields_are_rejected(field, value):
    import json
    body = json.loads(mb.encode(msg()))
    body[field] = value
    with pytest.raises(mb.BeaconError):
        mb.decode(json.dumps(body).encode())


def test_nan_and_deep_nesting_are_rejected():
    for raw in (b'{"k":"B","v":1,"i":NaN}', b"[" * 3000 + b"]" * 3000):
        with pytest.raises(mb.BeaconError):
            mb.decode(raw)


def test_seed_parsing_keeps_only_private_addresses():
    assert mb.parse_seeds(["192.168.1.5", " 10.0.0.2:4000 ", "8.8.8.8", "x", 5,
                           "192.168.1.5", "10.0.0.3:99999", "10.0.0.3:abc"]) == (
        "192.168.1.5", "10.0.0.2:4000")


hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402


@settings(max_examples=300, deadline=None, derandomize=True)
@given(st.binary(max_size=700))
def test_decode_only_raises_beacon_error(blob):
    try:
        mb.decode(blob)
    except mb.BeaconError:
        pass


# -- harness -----------------------------------------------------------------

def world(seed=1, **kw):
    return ms.SimWorld(seed, BeaconNode, **kw)


def events_of(node, kind):
    return [e for e in node.events if isinstance(e, kind)]


# -- join / leave budgets ------------------------------------------------------

@pytest.mark.parametrize("count", [2, 5, 20])
def test_join_visibility_budget(count):
    w = world(count)
    w.join(count - 1)
    w.assert_converged(5000)
    for _ in range(5):
        w.run(2.3)
        w.measure_join()
    joins = w.metrics["join_s"]
    w.assert_budget("join_typical_s", ms.percentile(joins, 50))
    w.assert_budget("join_p99_s", ms.percentile(joins, 99))
    assert w.check_invariants() == []


@pytest.mark.parametrize("count", [3, 20])
def test_clean_leave_is_fast_and_a_crash_is_noticed_by_expiry(count):
    w = world(count)
    w.join(count)
    w.assert_converged(5000)
    w.run(5)
    w.assert_budget("leave_clean_s", w.measure_leave(w.running()[0], clean=True))
    w.assert_budget("silent_loss_s", w.measure_leave(w.running()[0], clean=False))


def test_heartbeat_egress_budget_at_twenty_nodes():
    w = world(3)
    w.join(20)
    w.assert_converged(5000)
    w.run(40)
    assert w.egress_per_node(20) <= 500           # ticket: <= 0.5 KB/s heartbeats
    assert w.check_invariants() == []


def test_revision_change_reaches_everyone_within_one_round_trip():
    w = world(4)
    nodes = w.join(6)
    w.assert_converged(5000)
    w.run(5)
    w.add_target(nodes[2], "tv-1")
    assert w.time_to_converge(1.0) is not None
    ahead = [e for n in nodes if n is not nodes[2] for e in events_of(n.node, mb.RevAhead)]
    assert len(ahead) >= 5 and all(e.node_id == nodes[2].node_id for e in ahead)


# -- multicast blocked: seeds and gossip -------------------------------------

def test_without_seeds_a_multicast_blocked_network_cannot_discover():
    w = world(5)
    w.set_multicast(False)
    w.join(2)
    w.run(15)
    assert not w.converged()


def test_seed_address_connects_a_multicast_blocked_network():
    w = ms.SimWorld(5, BeaconNode, seeds=("192.168.1.10",))
    w.set_multicast(False)
    w.join(2)
    elapsed = w.time_to_converge(8.0)
    assert elapsed is not None and elapsed < 1.0 + mb.SEED_DELAY_S


def test_peer_list_gossip_discovers_members_that_only_know_the_seed():
    w = ms.SimWorld(6, BeaconNode)
    w.set_multicast(False)
    seed = w.add("seed")
    for index in range(5):
        w.add(f"m{index}", start=False)
    for handle in list(w.nodes.values())[1:]:
        w._node_kwargs = {"seeds": (seed.address,)}     # members know only the seed
        w.start(handle)
    assert w.time_to_converge(12.0) is not None
    member = w.nodes["m0"].node
    others = [e for e in events_of(member, mb.PeerSeen)
              if e.node_id not in {seed.node_id, member.node_id}]
    assert others                                      # learned via gossip hints
    assert w.check_invariants() == []


def test_unicast_heartbeats_keep_peers_alive_without_multicast():
    w = ms.SimWorld(7, BeaconNode, seeds=("192.168.1.10",))
    w.set_multicast(False)
    w.join(4)
    assert w.time_to_converge(12.0) is not None
    w.run(60)
    assert w.converged()                       # nobody expired


# -- wake / address change / duplicates --------------------------------------

def count_hellos(w, source):
    return sum(1 for _t, kind, src, dst, _s in w.net.log
               if kind == "send" and src == source and dst == "192.168.1.11")


def test_wake_and_address_change_trigger_a_burst_and_bump_incarnation():
    w = world(8)
    nodes = w.join(3)
    w.assert_converged(5000)
    w.run(10)
    before = nodes[0].node.local.incarnation
    w.sleep(nodes[0])
    w.run(30)
    w.wake(nodes[0])
    assert nodes[0].node.local.incarnation == before + 1
    assert w.time_to_converge(3.0) is not None
    old = nodes[1].address
    marker = len(w.net.log)
    new = w.change_ip(nodes[1])
    w.run(2.0)
    bursts = [e for e in w.net.log[marker:] if e[2] == new and e[1] == "send"
              and e[3] == nodes[2].address]
    assert len(bursts) >= 4                    # the 5-message HELLO burst
    assert w.time_to_converge(3.0) is not None
    moved = [e for n in (nodes[0], nodes[2]) for e in events_of(n.node, mb.PeerSeen)
             if e.why == "moved"]
    assert moved and all(e.address == new != old for e in moved)


def test_a_cloned_node_id_is_reported_as_a_duplicate_identity():
    w = world(9)
    first = w.add("orig")
    clone = w.add("clone")
    clone.node.node_id = first.node_id
    clone.node.local.node_id = first.node_id
    w.run(5)
    assert first.node.duplicates and first.node.duplicates[0].own
    assert first.node.duplicates[0].boot_id == clone.boot_id
    assert len(first.node.duplicates) == 1     # reported once, not per datagram


def test_a_stale_older_boot_does_not_overwrite_and_a_clash_is_reported_once():
    w = world(10)
    a, b = w.join(2)
    w.assert_converged(5000)
    other = b.node.beacon.peer(a.node_id)
    assert other is not None
    old = mb.Message("heartbeat", a.node_id, "9" * 32, 0, 99, other.boot_epoch - 100, 1,
                     "0" * 16)
    for _ in range(5):
        b.node.beacon._on_datagram(Datagram(a.address, mb.encode(old), True))
    dup = [e for e in b.node.events if isinstance(e, mb.DuplicateIdentity) and not e.own]
    assert len(dup) == 1 and b.node.beacon.stats.stale_boots == 5
    assert b.node.beacon.peer(a.node_id).boot_id == a.boot_id


def test_restart_is_reported_as_a_new_boot_not_a_new_node():
    w = world(11)
    a, b = w.join(2)
    w.assert_converged(5000)
    old_boot = a.boot_id
    w.restart(a)
    assert w.time_to_converge(3.0) is not None
    restarts = [e for e in events_of(b.node, mb.PeerSeen) if e.why == "restart"]
    assert len(restarts) == 1 and restarts[0].boot_id == a.boot_id != old_boot


# -- spoofing and abuse --------------------------------------------------------

def test_goodbye_is_honoured_only_from_the_known_boot_and_address():
    w = world(12)
    a, b, c = w.join(3)
    w.assert_converged(5000)
    victim = b.node.beacon.peer(a.node_id)
    for forged, src in ((mb.Message("goodbye", a.node_id, "9" * 32, 0, 0, 0, 1, "0" * 16),
                         a.address),                         # wrong boot id
                        (mb.Message("goodbye", a.node_id, a.boot_id, 0, 0, 0, 1, "0" * 16),
                         c.address),                         # wrong source address
                        (mb.Message("goodbye", "d" * 32, "e" * 32, 0, 0, 0, 1, "0" * 16),
                         a.address)):                        # unknown node
        b.node.beacon._on_datagram(Datagram(src, mb.encode(forged), True))
    assert b.node.beacon.peer(a.node_id) is victim
    assert b.node.beacon.stats.spoofed_goodbyes == 3
    real = mb.Message("goodbye", a.node_id, a.boot_id, 0, 0, 0, 1, "0" * 16)
    b.node.beacon._on_datagram(Datagram(a.address, mb.encode(real), True))
    assert b.node.beacon.peer(a.node_id) is None
    assert events_of(b.node, mb.PeerGone)


def test_own_beacons_are_ignored():
    w = world(13)
    a, _b = w.join(2)
    w.run(5)
    assert a.node.beacon.stats.ignored_own > 0
    assert not events_of(a.node, mb.PeerGone) and a.node.beacon.peer(a.node_id) is None


def test_non_lan_and_malformed_datagrams_are_dropped():
    w = world(14)
    a, _b = w.join(2)
    w.assert_converged(5000)
    beacon = a.node.beacon
    good = mb.encode(msg(node="d" * 32))
    beacon._on_datagram(Datagram("8.8.8.8", good, True))
    beacon._on_datagram(Datagram("192.168.1.77", b"x" * 900, True))
    beacon._on_datagram(Datagram("192.168.1.77", b"{not json", True))
    assert beacon.stats.ignored_source == 1 and beacon.stats.malformed == 2
    assert beacon.peer("d" * 32) is None


def test_a_flood_from_one_source_is_rate_limited():
    w = world(15)
    a, _b = w.join(2)
    w.assert_converged(5000)
    beacon = a.node.beacon
    before = len(a.node.events)
    for index in range(10_000):
        payload = mb.encode(msg(node=f"{index:032x}"))
        beacon._on_datagram(Datagram("192.168.1.200", payload, True))
    assert beacon.stats.rate_limited >= 9_900
    assert len(beacon.peers()) <= 2 + int(mb.RATE_CAPACITY) + 1
    assert len(a.node.events) - before < 60


def test_peer_table_is_bounded_and_established_peers_survive_a_sybil_flood():
    w = world(16)
    a, b = w.join(2)
    w.assert_converged(5000)
    beacon = a.node.beacon
    for index in range(300):
        payload = mb.encode(msg(node=f"{index + 1000:032x}"))
        beacon._on_datagram(Datagram(f"10.1.{index // 200}.{index % 200 + 1}", payload, True))
        w.run(0.5)
    assert len(beacon.peers()) <= mb.MAX_PEERS
    assert beacon.peer(b.node_id) is not None
    assert beacon.stats.refused_full > 0


def test_a_failing_event_callback_cannot_break_the_beacon():
    w = world(17)
    a, b = w.join(2)
    a.node.beacon._emit = lambda event: 1 / 0
    w.run(5)
    assert a.node.beacon.stats.callback_errors > 0
    assert a.node.beacon.peer(b.node_id) is not None


def test_close_is_idempotent_and_leaves_no_timers_or_handler():
    w = world(18)
    a, b = w.join(2)
    w.assert_converged(5000)
    w.stop(a, clean=True)
    w.stop(a, clean=True)
    a.node.beacon.close()
    sent = a.node.beacon.stats.sent
    w.run(30)
    assert a.node.beacon.stats.sent == sent
    assert b.node.beacon.peer(a.node_id) is None
    a.node.beacon.update_local(rev=99)               # no-op after close
    a.node.beacon.contact("192.168.1.50")
    w.run(5)
    assert a.node.beacon.stats.sent == sent


def test_welcome_replies_are_rate_limited_per_source():
    w = world(19)
    a, _b = w.join(2)
    w.assert_converged(5000)
    marker = len(w.net.log)
    hello = mb.encode(msg("hello", node="d" * 32))
    for _ in range(5):
        a.node.beacon._on_datagram(Datagram("192.168.1.150", hello, True))
    w.run(1.0)
    welcomes = [e for e in w.net.log[marker:] if e[2] == a.address and e[3] == "192.168.1.150"]
    assert len(welcomes) == 1


def test_updates_after_start_are_coalesced_into_one_heartbeat():
    w = world(20)
    a, _b = w.join(2)
    w.assert_converged(5000)
    w.run(5)
    sent = a.node.beacon.stats.sent
    for index in range(10):
        a.node.beacon.update_local(rev=100 + index)
    w.run(0.1)
    assert a.node.beacon.stats.sent - sent == 1 + len(a.node.beacon._unicast_peers())
    assert w.time_to_converge(1.0) is not None


def test_seeded_random_churn_with_the_beacon_node_converges_for_50_seeds():
    failures = ms.run_seeds(range(50), factory=BeaconNode)
    assert failures == [], failures[:2]
