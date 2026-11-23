"""The mesh simulator itself, plus budget proofs using the reference toy node (#395)."""
from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_ports
import mesh_sim as ms
from mesh_ports import Datagram


# -- virtual clock ---------------------------------------------------------

def test_clock_runs_events_in_order_and_honours_cancel():
    clock = ms.SimClock()
    seen = []
    clock.call_later(0.3, lambda: seen.append(("c", clock.now_ms)))
    clock.call_later(0.1, lambda: seen.append(("a", clock.now_ms)))
    timer = clock.call_later(0.2, lambda: seen.append(("x", clock.now_ms)))
    clock.call_later(0.1, lambda: seen.append(("b", clock.now_ms)))   # same time: FIFO
    timer.cancel()
    clock.advance(1.0)
    assert seen == [("a", 100), ("b", 100), ("c", 300)]
    assert clock.now_ms == 1000 and clock.pending == 0


def test_events_scheduled_by_events_run_in_the_same_advance():
    clock = ms.SimClock()
    seen = []

    def first():
        seen.append(clock.now_ms)
        clock.call_later(0.05, lambda: seen.append(clock.now_ms))
    clock.call_later(0.1, first)
    clock.advance(0.2)
    assert seen == [100, 150]


def test_clocks_and_transport_satisfy_the_production_ports():
    clock = ms.SimClock()
    world = ms.SimWorld(1)
    transport = world.net.attach("192.168.1.99")
    assert isinstance(clock, mesh_ports.Clock)
    assert isinstance(ms.NodeClock(clock), mesh_ports.Clock)
    assert isinstance(transport, mesh_ports.Transport)


def test_node_clock_suspend_pauses_monotonic_but_not_wall_and_runs_overdue_timers():
    base = ms.SimClock()
    node = ms.NodeClock(base, skew_s=100.0)
    fired = []
    node.call_later(1.0, lambda: fired.append(base.now_ms))
    base.advance(0.5)
    node.suspend()
    mono, wall = node.monotonic(), node.wall()
    base.advance(30.0)
    assert node.monotonic() == mono                 # frozen while asleep
    assert node.wall() == wall + 30.0               # wall clock jumped
    assert fired == []
    node.resume()
    assert fired == [30500]                         # overdue timer ran at wake
    assert node.monotonic() == pytest.approx(mono)
    assert node.wall() - base.wall() == 100.0       # skew applies to wall only


# -- network model ---------------------------------------------------------

class Inbox:
    def __init__(self, transport):
        self.items: list[tuple[int, Datagram]] = []
        transport.set_datagram_handler(lambda d: self.items.append((self.clock.now_ms, d)))


def pair(seed=1, **link):
    world = ms.SimWorld(seed)
    a, b = world.net.attach("10.0.0.1"), world.net.attach("10.0.0.2")
    boxes = {}
    for name, transport in (("a", a), ("b", b)):
        box = Inbox.__new__(Inbox)
        box.clock = world.clock
        box.items = []
        transport.set_datagram_handler(lambda d, box=box: box.items.append(
            (world.clock.now_ms, d)))
        boxes[name] = box
    if link:
        world.net.default_link = ms.LinkProfile(**link)
    return world, a, b, boxes


def test_unicast_latency_and_payload_are_delivered_intact():
    world, a, _b, boxes = pair(latency_ms=40, jitter_ms=0)
    a.send_unicast("10.0.0.2", b"hello")
    world.run(0.039)
    assert boxes["b"].items == []
    world.run(0.002)
    (when, datagram), = boxes["b"].items
    assert when == 40 and datagram == Datagram("10.0.0.1", b"hello", False)


def test_multicast_reaches_everyone_and_counts_egress_once():
    world = ms.SimWorld(2)
    transports = [world.net.attach(f"10.0.0.{i}") for i in range(1, 6)]
    counts = [0] * 5
    for index, transport in enumerate(transports):
        transport.set_datagram_handler(lambda d, i=index: counts.__setitem__(i, counts[i] + 1))
    transports[0].send_multicast(b"x" * 100)
    world.run(1)
    assert counts == [1, 1, 1, 1, 1]               # loopback on, like IP_MULTICAST_LOOP
    world.net.multicast_loopback = False
    transports[0].send_multicast(b"x" * 100)
    world.run(1)
    assert counts == [1, 2, 2, 2, 2]
    assert world.net.stats["10.0.0.1"].sent_bytes == 2 * (100 + ms.UDP_OVERHEAD)
    assert world.net.stats["10.0.0.2"].recv_bytes == 2 * (100 + ms.UDP_OVERHEAD)


def test_multicast_can_be_blocked_while_unicast_still_works():
    world, a, _b, boxes = pair()
    world.net.multicast_enabled = False
    a.send_multicast(b"m")
    a.send_unicast("10.0.0.2", b"u")
    world.run(1)
    assert [d.payload for _t, d in boxes["b"].items] == [b"u"]


def test_loss_is_seeded_and_roughly_the_configured_rate():
    def delivered(seed):
        world, a, _b, boxes = pair(seed, loss=0.3)
        for _ in range(2000):
            a.send_unicast("10.0.0.2", b"x")
        world.run(1)
        return len(boxes["b"].items)
    first = delivered(5)
    assert first == delivered(5)                      # deterministic
    assert 1200 < first < 1600                        # about 70 % of 2000
    assert first != delivered(6)


def test_partition_heal_offline_and_detach():
    world, a, b, boxes = pair()
    world.net.partition({"10.0.0.1"}, {"10.0.0.2"})
    a.send_unicast("10.0.0.2", b"1")
    world.run(0.1)
    assert boxes["b"].items == []
    world.net.heal()
    world.net.set_online("10.0.0.2", False)
    a.send_unicast("10.0.0.2", b"2")
    world.run(0.1)
    assert boxes["b"].items == []
    world.net.set_online("10.0.0.2", True)
    a.send_unicast("10.0.0.2", b"3")
    world.run(0.1)
    assert [d.payload for _t, d in boxes["b"].items] == [b"3"]
    b.close()
    b.close()                                         # idempotent
    a.send_unicast("10.0.0.2", b"4")
    world.run(0.1)
    assert len(boxes["b"].items) == 1


def test_in_flight_goodbye_survives_the_sender_going_offline():
    world, a, _b, boxes = pair(latency_ms=50, jitter_ms=0)
    a.send_multicast(b"bye")
    world.net.set_online("10.0.0.1", False)
    world.run(0.1)
    assert len(boxes["b"].items) == 1


def test_rebind_moves_the_address_and_rejects_collisions():
    world, a, _b, boxes = pair()
    world.net.rebind(a, "10.0.0.9")
    assert a.address == "10.0.0.9"
    a.send_unicast("10.0.0.2", b"x")
    world.run(0.1)
    assert boxes["b"].items[0][1].src == "10.0.0.9"
    with pytest.raises(ValueError):
        world.net.rebind(a, "10.0.0.2")


def test_bandwidth_cap_adds_serialisation_delay():
    world, a, _b, boxes = pair(latency_ms=0, jitter_ms=0, bandwidth_bps=8000)  # 1 KB/s
    a.send_unicast("10.0.0.2", b"x" * (1000 - ms.UDP_OVERHEAD))
    world.run(0.9)
    assert boxes["b"].items == []
    world.run(0.2)
    assert len(boxes["b"].items) == 1


def test_log_is_identical_for_the_same_seed_and_differs_for_another():
    def run(seed):
        world = ms.SimWorld(seed)
        world.join(4)
        world.run(10)
        return world.net.log
    assert run(11) == run(11)
    assert run(11) != run(12)


# -- request / response ----------------------------------------------------

def rpc_pair(seed=3, **link):
    world, a, b, _boxes = pair(seed, **link)
    b.set_request_handler(lambda src, payload: b"re:" + payload)
    return world, a, b


def test_request_reply_exactly_once_with_accounting():
    world, a, _b = rpc_pair()
    results = []
    a.request("10.0.0.2", b"ping", lambda r, e: results.append((r, e)), timeout=2)
    world.run(5)
    assert results == [(b"re:ping", None)]
    assert world.net.stats["10.0.0.1"].sent_bytes == 4 + ms.RPC_OVERHEAD
    assert world.net.stats["10.0.0.1"].recv_bytes == 7 + ms.RPC_OVERHEAD


@pytest.mark.parametrize("setup,expected", [
    ("partition", "timeout"), ("offline", "timeout"), ("refuse", "refused"),
    ("missing", "timeout"),
])
def test_request_failures_complete_exactly_once(setup, expected):
    world, a, b = rpc_pair()
    if setup == "partition":
        world.net.partition({"10.0.0.1"}, {"10.0.0.2"})
    elif setup == "offline":
        world.net.set_online("10.0.0.2", False)
    elif setup == "refuse":
        b.set_request_handler(lambda s, p: None)
    else:
        b.close()
    results = []
    a.request("10.0.0.2", b"x", lambda r, e: results.append((r, e)), timeout=1.5)
    world.run(5)
    assert results == [(None, expected)]


def test_request_on_a_closed_transport_fails_immediately():
    world, a, _b = rpc_pair()
    a.close()
    results = []
    a.request("10.0.0.2", b"x", lambda r, e: results.append((r, e)))
    assert results == [(None, "closed")]


def test_lossy_links_delay_rpcs_rather_than_failing_them():
    world, a, _b = rpc_pair(seed=9, loss=0.5, latency_ms=5, jitter_ms=0)
    done = []
    for _ in range(20):
        a.request("10.0.0.2", b"x", lambda r, e: done.append(e), timeout=30)
    world.run(30)
    assert done.count(None) == 20


# -- reference toy node: the harness can pass and fail budgets --------------

@pytest.mark.parametrize("count", [2, 5, 20])
def test_toy_node_meets_join_and_leave_budgets(count):
    world = ms.SimWorld(count)
    world.join(count - 1)
    world.assert_converged(5000)
    for _ in range(3):
        world.measure_join()
    joins = world.metrics["join_s"]
    world.assert_budget("join_typical_s", ms.percentile(joins, 50))
    world.assert_budget("join_p99_s", ms.percentile(joins, 99))
    leaver = world.running()[0]
    world.assert_budget("leave_clean_s", world.measure_leave(leaver, clean=True))
    crashed = world.running()[0]
    world.assert_budget("silent_loss_s", world.measure_leave(crashed, clean=False))
    assert world.check_invariants() == []


def test_target_visibility_and_egress_budget_at_twenty_nodes():
    world = ms.SimWorld(20)
    world.join(20)
    world.assert_converged(5000)
    world.run(15)
    world.assert_budget("target_visible_s", world.measure_target(world.running()[3], "tv-1"))
    world.run(20)
    world.assert_budget("egress_bytes_per_s_at_20_nodes", world.egress_per_node(10))
    report = world.report()
    assert report["nodes"] == 20 and report["target_visible_s"]["n"] == 1
    assert report["egress_bytes_per_s_per_node"] > 0


def test_a_slow_toy_fails_the_join_budget():
    world = ms.SimWorld(4, ms.ToyGossipNode, heartbeat=5.0, burst=False, reply=False)
    world.join(3)
    world.time_to_converge(30)
    started = world.clock.now_ms
    world.add()
    elapsed = world.time_to_converge(30)
    assert elapsed is not None and (world.clock.now_ms - started) > 1000
    with pytest.raises(ms.BudgetExceeded):
        world.assert_budget("join_typical_s", elapsed)


def test_blocked_multicast_cannot_converge_and_the_harness_says_so():
    world = ms.SimWorld(5)
    world.set_multicast(False)
    world.join(3)
    with pytest.raises(ms.BudgetExceeded) as error:
        world.assert_converged(5000)
    assert "missing=" in str(error.value)


def test_the_egress_budget_can_be_failed():
    world = ms.SimWorld(6, ms.ToyGossipNode, heartbeat=0.05)
    world.join(5)
    world.run(20)
    with pytest.raises(ms.BudgetExceeded):
        world.assert_budget("egress_bytes_per_s_at_20_nodes", world.egress_per_node(10))


def test_partition_heal_sleep_wake_and_ip_change_all_reconverge():
    world = ms.SimWorld(7)
    nodes = world.join(5)
    world.assert_converged(5000)
    world.partition(nodes[:2], nodes[2:])
    world.run(10)
    assert not world.converged()
    world.heal()
    world.assert_converged(3000)
    world.sleep(nodes[0])
    world.run(30)
    world.wake(nodes[0])
    world.assert_converged(3000)
    world.change_ip(nodes[1])
    world.assert_converged(3000)
    world.restart(nodes[2])
    world.assert_converged(3000)
    assert world.check_invariants() == []


def test_invariants_catch_a_node_that_never_forgets_the_dead():
    class Forgetful(ms.ToyGossipNode):
        ALIVE_FOR = 10 ** 9           # never expires peers

    world = ms.SimWorld(8, Forgetful)
    nodes = world.join(3)
    world.assert_converged(5000)
    world.crash(nodes[0])
    world.run(30)
    assert not world.converged()
    assert any("dead node" in problem for problem in world.check_invariants())


def test_seeded_random_scenarios_hold_for_100_seeds_quickly():
    started = time.perf_counter()
    failures = ms.run_seeds(range(100))
    assert failures == [], failures[:2]
    assert time.perf_counter() - started < 60


def test_a_broken_node_is_caught_by_the_seeded_property_suite():
    class NeverUpdates(ms.ToyGossipNode):
        def _on_datagram(self, datagram):
            pass                                 # ignores everyone

    failures = ms.run_seeds(range(5), factory=NeverUpdates)
    assert len(failures) >= 4        # a seed that leaves one node alive is trivially fine


def test_percentile_helper():
    assert ms.percentile([1, 2, 3, 4, 5], 50) == 3
    assert ms.percentile([5], 99) == 5
    with pytest.raises(ValueError):
        ms.percentile([], 50)
