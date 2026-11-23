"""Real event loop and UDP sockets on loopback only (#396). Everything is closed."""
from __future__ import annotations

from pathlib import Path
import random
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_beacon as mb
import mesh_udp
from mesh_ports import Datagram

LOOP = "127.0.0.1"


@pytest.fixture
def loop():
    value = mesh_udp.MeshLoop("smoothcast-mesh-test")
    value.start()
    yield value
    value.stop()
    assert not [t for t in threading.enumerate() if t.name == "smoothcast-mesh-test"]


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_loop_runs_timers_in_order_cancels_and_accepts_cross_thread_calls(loop):
    seen = []
    loop.call_later(0.15, lambda: seen.append("c"))
    loop.call_later(0.05, lambda: seen.append("a"))
    loop.call_later(0.10, lambda: seen.append("x")).cancel()
    loop.call_soon_threadsafe(lambda: seen.append("now"))
    assert wait_for(lambda: len(seen) == 3)
    assert seen == ["now", "a", "c"]
    assert loop.monotonic() > 0 and loop.wall() > 1_600_000_000


def test_a_failing_callback_is_counted_and_does_not_stop_the_loop():
    errors = []
    loop = mesh_udp.MeshLoop("smoothcast-mesh-test2", on_error=errors.append)
    loop.start()
    try:
        done = []
        loop.call_later(0.0, lambda: 1 / 0)
        loop.call_later(0.05, lambda: done.append(1))
        assert wait_for(lambda: done) and loop.errors == 1
        assert isinstance(errors[0], ZeroDivisionError)
    finally:
        loop.stop()
        loop.stop()                                   # idempotent


def test_transport_refuses_public_bind_addresses(loop):
    with pytest.raises(ValueError):
        mesh_udp.UdpTransport(loop, "8.8.8.8", 0)


def test_unicast_round_trip_and_close_is_clean(loop):
    a = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False)
    b = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False)
    got = []
    b.set_datagram_handler(got.append)
    a.send_unicast(f"{LOOP}:{b.port}", b"hello")
    assert wait_for(lambda: got)
    assert got[0] == Datagram(LOOP, b"hello", False)
    a.send_unicast("8.8.8.8:9", b"never")             # public targets are refused
    a.send_unicast("not-an-address", b"x")
    assert a.send_errors >= 1
    b.close()
    b.close()
    a.send_unicast(f"{LOOP}:{b.port}", b"after-close")
    time.sleep(0.1)
    assert len(got) == 1
    a.close()
    a.send_multicast(b"x")                            # harmless after close


def test_stand_in_multicast_fans_out_to_configured_peers(loop):
    a = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False)
    peers = [mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False) for _ in range(3)]
    inbox = []
    for peer in peers:
        peer.set_datagram_handler(inbox.append)
    a.stand_in_peers = [f"{LOOP}:{p.port}" for p in peers]
    a.send_multicast(b"hi")
    assert wait_for(lambda: len(inbox) == 3)
    for transport in (a, *peers):
        transport.close()


def test_request_reports_unsupported_until_sync_exists(loop):
    a = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False)
    result = []
    a.request("127.0.0.1", b"x", lambda r, e: result.append((r, e)))
    assert wait_for(lambda: result) and result == [(None, "unsupported")]
    a.close()


def test_real_multicast_when_the_host_supports_it(loop):
    try:
        a = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=True, group="239.255.83.99")
        b = mesh_udp.UdpTransport(loop, LOOP, a.port, multicast=True, group="239.255.83.99")
    except OSError:
        pytest.skip("loopback multicast is not available here")
    got = []
    b.set_datagram_handler(got.append)
    a.send_multicast(b"mc")
    arrived = wait_for(lambda: got, 2.0)
    a.close()
    b.close()
    if not arrived:
        pytest.skip("multicast packets are not routed on loopback here")
    assert got[0].multicast is True


def make_node(loop, name):
    transport = mesh_udp.UdpTransport(loop, LOOP, 0, multicast=False)
    local = mb.LocalState(name * 32, ("%s" % name) * 32, 1_700_000_000, 8801, rev=1)
    events = []
    beacon = mb.Beacon(clock=loop, transport=transport, rng=random.Random(ord(name)),
                       local=local, on_event=events.append)
    return transport, beacon, events


def test_two_beacons_find_each_other_and_say_goodbye_over_real_udp(loop):
    ta, ba, ea = make_node(loop, "a")
    tb, bb, eb = make_node(loop, "b")
    ta.stand_in_peers = [f"{LOOP}:{tb.port}"]
    tb.stand_in_peers = [f"{LOOP}:{ta.port}"]
    loop.call_soon_threadsafe(ba.start)
    loop.call_soon_threadsafe(bb.start)
    assert wait_for(lambda: any(isinstance(e, mb.PeerSeen) for e in ea)
                    and any(isinstance(e, mb.PeerSeen) for e in eb), 3.0)
    assert ea[0].node_id == "b" * 32 and ea[0].why == "new"
    bb_state = ba.peer("b" * 32)
    assert bb_state is not None and bb_state.address == LOOP
    # A revision bump is announced promptly.
    loop.call_soon_threadsafe(lambda: bb.update_local(rev=9))
    assert wait_for(lambda: any(isinstance(e, mb.RevAhead) and e.rev == 9 for e in ea), 3.0)
    # Clean shutdown: goodbye arrives and the peer is reported gone.
    loop.call_soon_threadsafe(bb.close)
    assert wait_for(lambda: any(isinstance(e, mb.PeerGone) for e in ea), 3.0)
    loop.call_soon_threadsafe(ba.close)
    assert wait_for(lambda: ta.closed and tb.closed)
    assert loop.errors == 0


def test_raw_garbage_from_a_socket_never_breaks_a_beacon(loop):
    ta, ba, ea = make_node(loop, "a")
    loop.call_soon_threadsafe(ba.start)
    raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for blob in (b"", b"\xff" * 2000, b"{}", b"[" * 500):
            raw.sendto(blob, (LOOP, ta.port))
        assert wait_for(lambda: ba.stats.malformed >= 3)
    finally:
        raw.close()
        loop.call_soon_threadsafe(ba.close)
        wait_for(lambda: ta.closed)
    assert ea == [] and loop.errors == 0
