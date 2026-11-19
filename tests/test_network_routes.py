"""P0 #14: deterministic no-GTK/no-network route diagnostic regressions."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import cli
import network_routes as routes
from server import HEALTH_BODY


class RouteSocket:
    def __init__(self, source="192.168.1.25", fail=False):
        self.source = source
        self.fail = fail
        self.target = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def connect(self, target):
        if self.fail:
            raise OSError("network unreachable")
        self.target = target

    def getsockname(self):
        return self.source, 39000


class ProbeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Health:
    def __init__(self, body=HEALTH_BODY):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, max_bytes):
        return self.body[:max_bytes]


def fake_route(stdout=None, returncode=0):
    data = stdout if stdout is not None else json.dumps(
        [{"dst": "192.168.1.41", "dev": "eth0", "prefsrc": "192.168.1.25"}]
    )
    return lambda argv, **kwargs: subprocess.CompletedProcess(argv, returncode, data)


def example(**overrides):
    config = {
        "socket_factory": lambda *args: RouteSocket(),
        "connect": lambda *args, **kwargs: ProbeConnection(),
        "open_url": lambda *args, **kwargs: Health(),
        "run": fake_route(),
        "os_name": "Linux",
    }
    config.update(overrides)
    return routes.report("192.168.1.41", **config)


def test_explicit_private_route_reports_source_interface_cast_port_and_hls_url():
    result = example()
    assert result["receiver_ip"] == "192.168.1.41"
    assert result["receiver_cast_tcp_port"] == 8009
    assert result["receiver_cast_port"] == "reachable"
    assert result["selected_source_ipv4"] == "192.168.1.25"
    assert result["selected_interface"] == "eth0"
    assert result["vpn_interface_suspected"] is False
    assert result["local_hls_health"] == "healthy"
    assert result["second_host_health_url"] == (
        "http://192.168.1.25:8767/_smoothcast/health"
    )
    assert result["inbound_hls_reachability"] == "not_verified_from_second_host"
    assert result["firewall_diagnosis"] == "unknown_without_second_host_test"
    assert any("does NOT prove" in line for line in result["interpretation"])


def test_routes_use_udp_connect_without_send_and_no_cast_commands():
    udp = RouteSocket()
    commands = []
    result = example(
        socket_factory=lambda *args: udp,
        connect=lambda destination, timeout: (
            commands.append((destination, timeout)) or ProbeConnection()
        ),
    )
    assert udp.target == ("192.168.1.41", 8009)
    assert commands == [(("192.168.1.41", 8009), 2)]
    assert result["receiver_cast_port"] == "reachable"


def test_lost_route_reports_no_source_and_does_not_probe_cast_port():
    with mock.patch.object(routes, "check_receiver_port") as port:
        result = example(socket_factory=lambda *a: RouteSocket(fail=True))
    port.assert_not_called()
    assert result["receiver_cast_port"] == "not_checked"
    assert result["second_host_health_url"] is None
    assert result["route_error"].startswith("Receiver route lookup failed")
    assert result["inbound_hls_reachability"] == "not_verified_from_second_host"


def test_vpn_interface_is_only_a_suspicion_not_a_firewall_verdict():
    probe = fake_route(
        json.dumps([{"prefsrc": "192.168.1.25", "dev": "tun0"}])
    )
    result = example(run=probe)
    assert result["selected_interface"] == "tun0"
    assert result["vpn_interface_suspected"] is True
    assert result["firewall_diagnosis"] == "unknown_without_second_host_test"


def test_invalid_or_mismatched_os_route_metadata_never_invents_an_interface():
    for stdout in ("garbage", "[]", '[{"dev": "eth0", "src": "10.0.0.3"}]'):
        result = example(run=fake_route(stdout))
        assert result["selected_interface"] is None
        assert result["vpn_interface_suspected"] is None
    result = example(os_name="Windows")
    assert result["selected_interface"] is None


def test_macos_route_get_parses_interface_without_shell():
    commands = []
    def mac(argv, **kwargs):
        commands.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "   interface: en0\n   gateway: 192.168.1.1\n")
    result = example(os_name="Darwin", run=mac)
    assert result["selected_interface"] == "en0"
    assert commands[0][0] == ["route", "-n", "get", "192.168.1.41"]
    assert commands[0][1]["timeout"] == 2


def test_cast_port_failure_distinguishes_offline_or_filtered_without_guessing_why():
    def fail(*args, **kwargs):
        raise ConnectionRefusedError("refused")
    result = example(connect=fail)
    assert result["receiver_cast_port"] == "unreachable_or_filtered"
    assert result["firewall_diagnosis"] == "unknown_without_second_host_test"


def test_local_hls_health_is_exact_and_time_bounded():
    opened = []
    def open_url(url, *, timeout):
        opened.append((url, timeout))
        return Health(HEALTH_BODY)
    result = example(open_url=open_url)
    assert result["local_hls_health"] == "healthy"
    assert opened == [("http://127.0.0.1:8767/_smoothcast/health", 2)]
    result = example(open_url=lambda *a, **k: Health(b"wrong owner"))
    assert result["local_hls_health"] == "unexpected_response"
    def outage(*args, **kwargs):
        raise OSError("connection refused")
    result = example(open_url=outage)
    assert result["local_hls_health"] == "not_responding"


def test_public_or_loopback_targets_rejected_before_network_access():
    for target in ("8.8.8.8", "127.0.0.1", "169.254.1.5", "localhost", ""):
        with pytest.raises(ValueError):
            routes.report(
                target,
                socket_factory=lambda *a: pytest.fail("network attempted"),
            )


def test_no_public_health_url_if_selected_source_is_not_private():
    result = example(
        socket_factory=lambda *a: RouteSocket(source="203.0.113.7"),
    )
    assert result["second_host_health_url"] is None
    assert result["selected_source_ipv4"] == "203.0.113.7"


def test_cli_diagnostic_path_is_explicit_and_never_opens_gtk():
    with mock.patch.object(sys, "argv", ["smoothcast", "--network-check", "192.168.1.41"]), \
         mock.patch.dict("os.environ", {"SMOOTHCAST_TEST_CONTEXT": "1"}), \
         mock.patch.object(routes, "main", return_value=0) as main:
        assert cli.main() == 0
    main.assert_called_once_with(["192.168.1.41"])
    with mock.patch.object(sys, "argv", ["smoothcast", "--version"]):
        assert cli.main() == 0
