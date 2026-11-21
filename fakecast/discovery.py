"""Loopback-only Google Cast mDNS advertisement for the protocol fake."""
from __future__ import annotations

import socket
import uuid

from zeroconf import ServiceInfo, Zeroconf


SERVICE_TYPE = "_googlecast._tcp.local."


class CastAdvertiser:
    """Advertise a fake receiver on the specified local interface only."""

    def __init__(
        self, host: str, port: int, profile: str, *, identifier: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.profile = profile
        self.identifier = identifier or uuid.uuid4().hex
        self.service_name = f"{self.identifier}.{SERVICE_TYPE}"
        self.zeroconf: Zeroconf | None = None
        self.error: str | None = None

    @property
    def active(self) -> bool:
        return self.zeroconf is not None

    def start(self) -> None:
        if self.active:
            return
        zc: Zeroconf | None = None
        try:
            zc = Zeroconf(interfaces=[self.host])
            info = ServiceInfo(
                SERVICE_TYPE,
                self.service_name,
                addresses=[socket.inet_aton(self.host)],
                port=self.port,
                properties={
                    b"id": self.identifier.encode("ascii"),
                    b"fn": f"SmoothCast Test ({self.profile})".encode("utf-8"),
                    b"md": self.profile.encode("ascii"),
                    b"ve": b"1",
                    b"ca": b"0x7ff",
                    b"st": b"0",
                },
                server=f"{self.identifier}.local.",
            )
            zc.register_service(info)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            if zc is not None:
                zc.close()
            return
        self.zeroconf = zc
        self.error = None

    def stop(self) -> None:
        zc, self.zeroconf = self.zeroconf, None
        if zc is not None:
            zc.unregister_all_services()
            zc.close()
