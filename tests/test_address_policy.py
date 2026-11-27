import address_policy as a


def test_ipv6_url_is_bracketed_and_zone_stripped():
    assert a.url("http", "2001:db8::5", 8000) == "http://[2001:db8::5]:8000/"
    assert a.url("http", "[fd00::1%eth0]", 80, "x") == "http://[fd00::1]:80/x"


def test_link_local_loopback_and_junk_refused():
    for bad in ("fe80::1%eth0", "fe80::1", "127.0.0.1", "::1", "0.0.0.0", "224.0.0.1", "nope", None):
        assert a.host_for_url(bad) is None, bad
    assert a.url("http", "192.168.1.5", 0) is None
    assert a.url("http", "192.168.1.5", 8000, "/p") == "http://192.168.1.5:8000/p"


def test_source_ranking_prefers_private_ipv4_by_default():
    order = sorted(["2001:db8::1", "192.168.1.9", "fd00::2", "fe80::1", "8.8.8.8"], key=a.rank_source)
    assert order[0] == "192.168.1.9" and order[-1] == "fe80::1"
    assert a.rank_source("fd00::2", prefer_ipv6=True) < a.rank_source("192.168.1.9", prefer_ipv6=True)


def test_interface_scoring_and_vpn_warning():
    assert a.interface_kind("wg0") == "vpn" and a.interface_kind("docker0") == "virtual"
    assert a.interface_kind("enp3s0") == "physical" and a.interface_kind("wlan0") == "physical"
    assert a.score_interface("enp3s0") > a.score_interface("wg0") > a.score_interface("docker0")
    assert a.score_interface("tun0", is_route_to_receiver=True) == 100
    assert "VPN" in a.route_warning("tailscale0") and a.route_warning("eth0") is None
