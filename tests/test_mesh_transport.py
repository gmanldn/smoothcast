"""Real TLS loopback tests for native peer identity and request handling."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import shutil
import socket
import ssl
import subprocess
import threading

import pytest

from mesh_transport import NativePeerConnection, PeerEndpoint, PeerProtocolError


@pytest.fixture
def identities(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required to generate temporary TLS identities")
    result = []
    for name in ("approved", "replacement"):
        cert, key = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
        subprocess.run([
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=SmoothCast loopback test", "-keyout", str(key), "-out", str(cert),
        ], check=True, capture_output=True, timeout=10)
        pem = cert.read_text(encoding="ascii")
        result.append((cert, key, pem, sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()))
    return result


@pytest.fixture
def serve(monkeypatch):
    original_connect = socket.create_connection
    endpoints = {}

    def loopback(address, *args, **kwargs):
        return original_connect(("127.0.0.1", endpoints[address]), *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback)
    running = []
    requests = []

    def start(endpoint, identity, *, status=200, payload=b'{"paired": true}'):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                requests.append((self.path, json.loads(self.rfile.read(
                    int(self.headers["Content-Length"])))))
                self.send_response(status)
                if status == 307:
                    self.send_header("Location", "https://192.168.2.20:8888/")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        cert, key, *_ = identity
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        endpoints[(endpoint.address, endpoint.port)] = server.server_port
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                                  daemon=True)
        worker.start()
        running.append((server, worker))
        return requests

    yield start
    for server, worker in running:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_pin_authenticates_native_peer_after_address_change(serve, identities):
    approved, _ = identities
    for address in ("192.168.1.10", "192.168.2.10"):
        endpoint = PeerEndpoint(address, 8888)
        requests = serve(endpoint, approved)
        conn = NativePeerConnection(endpoint, approved[2], approved[3])
        assert conn.post_json("pair", {"challenge": "test"}) == {"paired": True}
    assert requests == [("/mesh/v1/pair", {"challenge": "test"})] * 2


def test_replacement_certificate_receives_no_http_body(serve, identities):
    approved, replacement = identities
    endpoint = PeerEndpoint("192.168.1.10", 8888)
    requests = serve(endpoint, replacement)
    conn = NativePeerConnection(endpoint, approved[2], approved[3])
    with pytest.raises(ssl.SSLCertVerificationError):
        conn.post_json("pair", {"challenge": "must not be sent"})
    assert not requests
    with pytest.raises(ValueError, match="approved fingerprint"):
        NativePeerConnection(endpoint, replacement[2], approved[3])


@pytest.mark.parametrize("status,payload,message", [
    (307, b"{}", "HTTP 307"),
    (200, b" " * (64 * 1024 + 1), "too large"),
    (200, b"<html>", "Invalid native peer JSON"),
])
def test_peer_refuses_redirects_and_invalid_replies(serve, identities, status, payload, message):
    approved, _ = identities
    endpoint = PeerEndpoint("192.168.1.10", 8888)
    requests = serve(endpoint, approved, status=status, payload=payload)
    conn = NativePeerConnection(endpoint, approved[2], approved[3])
    with pytest.raises(PeerProtocolError, match=message):
        conn.post_json("pair", {})
    assert requests == [("/mesh/v1/pair", {})]


@pytest.mark.parametrize("address,port", [
    ("127.0.0.1", 8888), ("169.254.2.3", 8888), ("8.8.8.8", 8888),
    ("smoothcast.local", 8888), ("192.168.1.10", 0), ("192.168.1.10", True),
])
def test_candidate_endpoint_must_be_private_numeric_and_have_a_valid_port(address, port):
    with pytest.raises(ValueError):
        PeerEndpoint(address, port)
