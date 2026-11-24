"""Public-only egress: policy table, rebinding, mixed answers, quotas (#588)."""
from __future__ import annotations

import socket
import threading

import link_egress as eg
import pytest


@pytest.mark.parametrize("address", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111", "2a00:1450:4009:81f::200e"])
def test_public_addresses_pass(address):
    assert eg.is_public_address(address)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.255.255.254", "10.0.0.1", "172.16.5.4", "172.31.255.255", "192.168.1.1",
    "169.254.169.254", "169.254.0.1", "100.64.0.1", "0.0.0.0", "255.255.255.255", "224.0.0.1",
    "239.255.255.250", "192.0.0.8", "198.18.0.1", "240.0.0.1",
    "::1", "::", "fe80::1", "fd00::1", "fc00::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::", "2002:a9fe:a9fe::",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    "not-an-ip", "", "1.2.3", "8.8.8.8/32", None, 5, "8.8.8.8 ", "0x7f.1", "2130706433"])
def test_everything_else_is_denied(address):
    assert not eg.is_public_address(address)


def answers(*addresses):
    def resolver(host, port, type=None):
        return [((socket.AF_INET6 if ":" in a else socket.AF_INET), socket.SOCK_STREAM, 6, "",
                 (a, port)) for a in addresses]
    return resolver


def test_every_answer_must_be_public_mixed_answers_are_a_rebinding_attempt():
    assert eg.resolve_public("ok.test", 443, answers("8.8.8.8", "2606:4700::1111"))
    for bad in (("8.8.8.8", "127.0.0.1"), ("10.1.1.1",), ("169.254.169.254",), ("::1", "8.8.8.8")):
        with pytest.raises(eg.EgressDenied):
            eg.resolve_public("evil.test", 443, answers(*bad))


@pytest.mark.parametrize("host,port", [("", 443), ("a b", 443), ("x/y", 443), ("u@h", 443),
                                       ("ok.test", 22), ("ok.test", 8080), ("ok.test", 0), ("a" * 300, 443)])
def test_bad_hosts_and_ports_are_refused_before_any_lookup(host, port):
    def resolver(*a, **k):
        raise AssertionError("must not resolve")

    with pytest.raises(eg.EgressDenied):
        eg.resolve_public(host, port, resolver)


def test_unresolvable_names_are_denied():
    def resolver(*a, **k):
        raise socket.gaierror("nope")

    with pytest.raises(eg.EgressDenied):
        eg.resolve_public("nx.test", 443, resolver)


class Origin:
    """A local TCP echo server standing in for the public site."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo(conn):
        with conn:
            while data := conn.recv(4096):
                conn.sendall(data.upper())


def connect_via(path, target):
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(5)
    client.connect(path)
    client.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    reply = b""
    while b"\r\n\r\n" not in reply:
        chunk = client.recv(1024)
        if not chunk:
            break
        reply += chunk
    return client, reply.split(b"\r\n", 1)[0].decode()


@pytest.fixture
def proxy(tmp_path):
    origin = Origin()
    seen = []

    def connector(family, address, port):
        seen.append((address, port))
        return socket.create_connection(("127.0.0.1", origin.port), timeout=3)  # the "public" site

    p = eg.EgressProxy(tmp_path / "egress.sock", resolver=answers("93.184.216.34"), connector=connector)
    p.seen = seen
    yield p
    p.close()
    origin.sock.close()


def test_connect_to_a_public_name_tunnels_to_the_pinned_ip_only(proxy):
    client, status = connect_via(proxy.path, "video.example:443")
    assert status.endswith("200 Connection Established")
    client.sendall(b"hello")
    assert client.recv(64) == b"HELLO"
    client.close()
    assert proxy.seen == [("93.184.216.34", 443)]  # the checked address, never a re-resolved one


@pytest.mark.parametrize("target", ["127.0.0.1:443", "10.0.0.5:443", "169.254.169.254:80",
                                    "[::1]:443", "[fd00::1]:443", "[::ffff:127.0.0.1]:443",
                                    "metadata.google.internal:80"])
def test_non_public_literals_are_forbidden_without_connecting(tmp_path, target):
    calls = []
    p = eg.EgressProxy(tmp_path / "e.sock", resolver=lambda h, port, type=None: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))],
        connector=lambda *a: calls.append(a))
    try:
        _, status = connect_via(p.path, target)
        assert "403" in status and calls == [] and p.denied == 1
    finally:
        p.close()


def test_dns_rebinding_cannot_swap_the_address_after_the_check(tmp_path):
    lookups = []

    def rebinding(host, port, type=None):
        lookups.append(host)  # first lookup is public; any later one would be private
        address = "93.184.216.34" if len(lookups) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    connected = []

    def connector(family, address, port):
        connected.append(address)
        raise OSError("no route")

    p = eg.EgressProxy(tmp_path / "e.sock", resolver=rebinding, connector=connector)
    try:
        _, status = connect_via(p.path, "rebind.example:443")
        assert "502" in status and connected == ["93.184.216.34"] and len(lookups) == 1
    finally:
        p.close()


def test_a_redirect_style_second_connection_is_checked_again(tmp_path):
    state = {"n": 0}

    def resolver(host, port, type=None):
        state["n"] += 1
        address = "93.184.216.34" if host == "first.example" else "10.0.0.9"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    p = eg.EgressProxy(tmp_path / "e.sock", resolver=resolver, connector=lambda *a: socket.create_connection(
        ("127.0.0.1", Origin().port)))
    try:
        c1, ok = connect_via(p.path, "first.example:443")
        c1.close()
        _, denied = connect_via(p.path, "internal.example:443")
        assert "200" in ok and "403" in denied
    finally:
        p.close()


@pytest.mark.parametrize("request_line", [b"GET http://8.8.8.8/ HTTP/1.1", b"POST / HTTP/1.1",
                                          b"CONNECT nonsense HTTP/1.1", b"CONNECT a:b:c HTTP/1.1",
                                          b"CONNECT video.example:22 HTTP/1.1"])
def test_only_well_formed_connect_to_allowed_ports_is_served(proxy, request_line):
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(5)
    client.connect(proxy.path)
    client.sendall(request_line + b"\r\n\r\n")
    status = client.recv(256).split(b"\r\n", 1)[0]
    client.close()
    assert not status.endswith(b"200 Connection Established") and proxy.seen == []


def test_per_tunnel_byte_quota_cuts_the_connection(tmp_path):
    origin = Origin()
    p = eg.EgressProxy(tmp_path / "e.sock", resolver=answers("93.184.216.34"), max_bytes=1000,
                       connector=lambda *a: socket.create_connection(("127.0.0.1", origin.port)))
    try:
        client, status = connect_via(p.path, "video.example:443")
        assert "200" in status
        received = 0
        try:
            for _ in range(200):
                client.sendall(b"x" * 512)
                chunk = client.recv(4096)
                if not chunk:
                    break
                received += len(chunk)
        except OSError:
            pass
        assert received < 200 * 512  # the tunnel was cut well before the transfer finished
    finally:
        p.close()
        origin.sock.close()


def test_socket_is_private_and_removed_on_close(tmp_path):
    p = eg.EgressProxy(tmp_path / "e.sock", resolver=answers("8.8.8.8"))
    import os
    import stat
    assert stat.S_IMODE(os.stat(p.path).st_mode) == 0o600
    p.close()
    assert not os.path.exists(p.path)
