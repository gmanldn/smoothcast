"""Authenticated HTTPS connections for native SmoothCast peers."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from http.client import HTTPSConnection
from ipaddress import IPv4Address, IPv4Network
import re
import ssl

_LAN_NETWORKS = tuple(IPv4Network(block) for block in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
_CERTIFICATE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----"
)
_PIN = re.compile(r"[0-9a-f]{64}")
_CONNECT_TIMEOUT = 3.0
_MAX_MESSAGE_BYTES = 64 * 1024


class PeerProtocolError(RuntimeError):
    """An authenticated peer returned an unsupported reply."""


@dataclass(frozen=True)
class PeerEndpoint:
    """One candidate native endpoint. Discovery supplies no trust."""

    address: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.address, str):
            raise ValueError("Expected a numeric private LAN address")
        address = IPv4Address(self.address)
        if not any(address in network for network in _LAN_NETWORKS):
            raise ValueError("Expected a numeric private LAN address")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Peer port must be between 1 and 65535")


class NativePeerConnection(HTTPSConnection):
    """Connect using only the approved peer certificate as a trust anchor.

    Pairing must obtain the fingerprint independently of the candidate
    certificate and LAN advertisement. The endpoint may change without
    changing the approved identity. http.client leaves redirects to its caller.
    """

    def __init__(self, endpoint: PeerEndpoint, certificate_pem: str,
                 approved_fingerprint: str) -> None:
        if not _PIN.fullmatch(approved_fingerprint):
            raise ValueError("Expected a SHA-256 certificate fingerprint")
        pem = certificate_pem.strip()
        if len(pem) > 8192 or not _CERTIFICATE.fullmatch(pem):
            raise ValueError("Expected one peer certificate in PEM form")
        der = ssl.PEM_cert_to_DER_cert(pem)
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), approved_fingerprint):
            raise ValueError("Peer certificate does not match the approved fingerprint")

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # The exact leaf certificate identifies the peer even if its IP changes.
        context.check_hostname = False
        context.load_verify_locations(cadata=pem)
        self._approved_certificate = der
        super().__init__(endpoint.address, endpoint.port,
                         timeout=_CONNECT_TIMEOUT, context=context)

    def set_tunnel(self, *args, **kwargs) -> None:
        raise ValueError("Native peer connections must connect directly")

    def connect(self) -> None:
        try:
            super().connect()
            if (not isinstance(self.sock, ssl.SSLSocket)
                    or self.sock.getpeercert(binary_form=True) != self._approved_certificate):
                raise ssl.SSLCertVerificationError("Unexpected SmoothCast peer certificate")
        except BaseException:
            self.close()
            raise

    def post_json(self, operation: str, fields: dict[str, object]) -> dict[str, object]:
        """Exchange bounded JSON on the native API without following redirects."""
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", operation):
            raise ValueError("Invalid native peer operation")
        body = json.dumps(fields, allow_nan=False).encode("utf-8")
        if len(body) > _MAX_MESSAGE_BYTES:
            raise ValueError("Native peer request is too large")
        try:
            self.request("POST", f"/mesh/v1/{operation}", body, {
                "Content-Type": "application/json", "Accept": "application/json",
            })
            with self.getresponse() as response:
                if response.status != 200:
                    raise PeerProtocolError(f"Native peer returned HTTP {response.status}")
                content_type = response.getheader("Content-Type", "").split(";", 1)[0]
                if content_type.strip().lower() != "application/json":
                    raise PeerProtocolError("Native peer response is not JSON")
                data = response.read(_MAX_MESSAGE_BYTES + 1)
                if len(data) > _MAX_MESSAGE_BYTES:
                    raise PeerProtocolError("Native peer reply is too large")
            try:
                result = json.loads(data)
            except (ValueError, RecursionError) as exc:
                raise PeerProtocolError("Invalid native peer JSON") from exc
            if not isinstance(result, dict):
                raise PeerProtocolError("Expected a native peer JSON object")
            return result
        finally:
            self.close()
