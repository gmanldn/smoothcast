"""Bounded, local-only discovery of other SmoothCast room hosts."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import secrets
import socket
import threading
import time
from typing import Any

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

SERVICE_TYPE = "_smoothcast._tcp.local."
PROTOCOL_VERSION = 1
PEER_TTL_SECONDS = 45
MAX_PEERS = 64
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_INSTANCE_ID = re.compile(r"^[a-f0-9]{32}$")
_DNS_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
LOCAL_CAPABILITIES = ("room", "video-upload", "remote-cast", "screens")


@dataclass(frozen=True)
class Peer:
    instance_id: str
    name: str
    address: str
    port: int
    version: int
    capabilities: tuple[str, ...]
    last_seen: float

    @property
    def compatible(self) -> bool:
        return self.version == PROTOCOL_VERSION

    def public(self) -> dict[str, Any]:
        return {
            "id": self.instance_id,
            "name": self.name,
            "version": self.version,
            "compatible": self.compatible,
            "capabilities": list(self.capabilities),
            "url": f"http://{self.address}:{self.port}/",
        }


def parse_peer(instance_id: object, name: object, version: object,
               capabilities: object, addresses: object, port: object,
               *, now: float, own_id: str = "") -> Peer | None:
    """Validate untrusted service data and choose one private IPv4 endpoint."""
    if not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id):
        return None
    if instance_id == own_id:
        return None
    if not isinstance(name, str) or not _DNS_NAME.fullmatch(name):
        return None
    if (not isinstance(version, str) or not 1 <= len(version) <= 5
            or not version.isascii() or not version.isdecimal()):
        return None
    parsed_version = int(version)
    if parsed_version < 1 or parsed_version > 65535:
        return None
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return None
    if isinstance(capabilities, str):
        caps = tuple(sorted({part for part in capabilities.split(",")
                             if part in LOCAL_CAPABILITIES}))
    else:
        caps = ()
    if not isinstance(addresses, (list, tuple)):
        return None
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(address, ipaddress.IPv4Address) and any(
                address in network for network in _PRIVATE_NETWORKS):
            return Peer(instance_id, name, str(address), port,
                        parsed_version, caps, now)
    return None


class PeerDirectory(ServiceListener):
    """Advertise this room and keep a bounded, expiring list of LAN peers."""

    def __init__(self, bind_ip: str, name: str, port: int, *, instance_id: str | None = None,
                 clock=time.monotonic, zeroconf: Zeroconf | None = None) -> None:
        try:
            address = ipaddress.IPv4Address(bind_ip)
        except ipaddress.AddressValueError as exc:
            raise ValueError("bind_ip must be a private IPv4 address") from exc
        if not any(address in network for network in _PRIVATE_NETWORKS):
            raise ValueError("bind_ip must be a private IPv4 address")
        if not isinstance(name, str) or not _DNS_NAME.fullmatch(name):
            raise ValueError("name must be a lowercase DNS label")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be in the valid TCP port range")
        self.instance_id = instance_id or secrets.token_hex(16)
        if not _INSTANCE_ID.fullmatch(self.instance_id):
            raise ValueError("instance_id must be 128-bit lowercase hex")
        self.name = name
        self._clock = clock
        self._lock = threading.RLock()
        self._peers: dict[str, Peer] = {}
        self._closed = False
        self._owns_zeroconf = zeroconf is None
        self._zc: Zeroconf | None = zeroconf
        self._browser: ServiceBrowser | None = None
        self._service: ServiceInfo | None = None
        try:
            if self._zc is None:
                self._zc = Zeroconf(interfaces=[bind_ip])
            self._service = ServiceInfo(
                SERVICE_TYPE,
                f"{self.name}-{self.instance_id[:8]}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(bind_ip)],
                port=port,
                host_ttl=PEER_TTL_SECONDS,
                other_ttl=PEER_TTL_SECONDS,
                properties={
                    "id": self.instance_id,
                    "name": self.name,
                    "version": str(PROTOCOL_VERSION),
                    "capabilities": ",".join(LOCAL_CAPABILITIES),
                },
                server=f"{self.name}.local.",
            )
            self._zc.register_service(self._service)
            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE, listener=self)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _text(properties: dict, key: str) -> str:
        value = properties.get(key.encode("ascii"), properties.get(key, ""))
        if isinstance(value, bytes):
            return value.decode("utf-8", "strict")
        return value if isinstance(value, str) else ""

    def add_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self._load_service(zeroconf, service_type, name)

    def update_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self._load_service(zeroconf, service_type, name)

    def remove_service(self, _zeroconf: Zeroconf, _service_type: str, name: str) -> None:
        with self._lock:
            self._peers.pop(name, None)

    def _load_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=1000)
            if info is None:
                return
            properties = info.properties or {}
            peer = parse_peer(
                self._text(properties, "id"), self._text(properties, "name"),
                self._text(properties, "version"),
                self._text(properties, "capabilities"), info.parsed_addresses(),
                info.port, now=self._clock(), own_id=self.instance_id,
            )
        except Exception:
            return
        if peer is None:
            return
        with self._lock:
            if self._closed:
                return
            self._peers[name] = peer
            if len(self._peers) > MAX_PEERS:
                oldest = min(self._peers, key=lambda service: self._peers[service].last_seen)
                del self._peers[oldest]

    def snapshot(self) -> list[dict[str, Any]]:
        # Zeroconf refreshes cached records and emits removals on goodbye or
        # DNS expiry. An unchanged live record need not emit update callbacks.
        with self._lock:
            unique: dict[str, Peer] = {}
            for peer in self._peers.values():
                current = unique.get(peer.instance_id)
                if current is None or peer.last_seen >= current.last_seen:
                    unique[peer.instance_id] = peer
            peers = sorted(unique.values(), key=lambda item: (item.name.casefold(), item.instance_id))
            return [peer.public() for peer in peers]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._peers.clear()
        browser, self._browser = self._browser, None
        if browser is not None:
            try:
                browser.cancel()
            except Exception:
                pass
        zeroconf = self._zc
        if zeroconf is not None:
            try:
                if self._service is not None:
                    zeroconf.unregister_service(self._service)
            except Exception:
                pass
            self._zc = None
            if self._owns_zeroconf:
                try:
                    zeroconf.close()
                except Exception:
                    pass
