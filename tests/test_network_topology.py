import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import errors
from network_topology import Iface, diagnose

LAN = Iface("eth0", "192.168.1.20/24", default_route=True)
TV = "192.168.1.50"


def d(ifaces, ip=TV, **kw):
    base = dict(tcp_ok=False, discovery_ok=False)
    return diagnose(ifaces, ip, **{**base, **kw})


def test_healthy_and_reachable_but_undiscoverable():
    assert d([LAN], tcp_ok=True, discovery_ok=True) is None
    assert d([LAN], tcp_ok=True) == "network.discovery_blocked"


def test_each_topology_gets_its_own_catalogued_code():
    vpn = Iface("tun0", "10.8.0.2/24", vpn=True, default_route=True)
    cases = {
        "network.subnet_mismatch": d([Iface("eth0", "10.0.0.5/24", default_route=True)]),
        "network.vpn_default_route": d([Iface("eth0", "10.0.0.5/24"), vpn]),
        "network.client_isolation": d([LAN], peer_arp_seen=False),
        "network.interface_ambiguous": d([LAN, Iface("wlan0", "192.168.1.21/24"), Iface("eth1", "172.16.0.2/24", default_route=True)]),
    }
    for code, got in cases.items():
        assert got == code and code in errors.CATALOGUE


def test_ipv6_and_garbage_inputs_never_raise():
    assert d([Iface("e", "fd00::2/64")], ip="fd00::9", tcp_ok=True) == "network.discovery_blocked"
    assert d([Iface("e", "not-a-cidr")], ip="nonsense") == "network.subnet_mismatch"
    assert d([LAN], ip="fd00::9") == "network.subnet_mismatch"
