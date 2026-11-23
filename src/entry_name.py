"""The house's single address: ``smoothcast.local`` (issue #419).

Only the primary node claims the name; when the primary changes the new one
registers it and the old one lets go, so one stable address keeps working as
computers sleep and wake. On a name conflict (another device already owns it)
the node falls back to ``smoothcast-2.local`` ... ``smoothcast-5.local``.
Registration is best effort and never raises.
"""
from __future__ import annotations

import socket
import threading
from typing import Callable

import lan_guard

SERVICE_TYPE = "_http._tcp.local."
MAX_ALTERNATES = 5


def candidate_names(base: str = lan_guard.ENTRY_NAME) -> list[str]:
    """``smoothcast.local`` first, then deterministic numbered alternatives."""
    stem = base[:-len(".local")] if base.endswith(".local") else base
    return [base] + [f"{stem}-{n}.local" for n in range(2, MAX_ALTERNATES + 1)]


class EntryName:
    def __init__(self, bind_ip: str, port: int, *,
                 zeroconf_factory: Callable[[str], object] | None = None,
                 info_factory: Callable[..., object] | None = None) -> None:
        self.bind_ip, self.port = bind_ip, port
        self._zc_factory = zeroconf_factory
        self._info_factory = info_factory
        self._zc: object | None = None
        self._info: object | None = None
        self._lock = threading.Lock()
        self.name: str | None = None          # the name currently held, if any

    # -- public -----------------------------------------------------------
    def apply(self, is_primary: bool) -> None:
        """Claim the name when primary, release it otherwise."""
        with self._lock:
            if is_primary and self.name is None:
                self._claim()
            elif not is_primary and self.name is not None:
                self._release()

    def close(self) -> None:
        with self._lock:
            self._release()

    @property
    def url(self) -> str | None:
        return f"http://{self.name}:{self.port}/" if self.name else None

    # -- internals --------------------------------------------------------
    def _factories(self) -> tuple[Callable[[str], object], Callable[..., object]] | None:
        if self._zc_factory is not None and self._info_factory is not None:
            return self._zc_factory, self._info_factory
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            return None
        return (lambda ip: Zeroconf(interfaces=[ip]), ServiceInfo)

    def _claim(self) -> None:
        factories = self._factories()
        if factories is None:
            return
        make_zc, make_info = factories
        try:
            zeroconf = make_zc(self.bind_ip)
        except Exception:
            return
        for name in candidate_names():
            try:
                info = make_info(
                    SERVICE_TYPE, f"SmoothCast house ({name}).{SERVICE_TYPE}",
                    addresses=[socket.inet_aton(self.bind_ip)], port=self.port,
                    properties={"path": "/", "entry": name}, server=f"{name}.")
                zeroconf.register_service(info)             # type: ignore[attr-defined]
            except Exception:
                continue                                    # taken or refused: try the next name
            self._zc, self._info, self.name = zeroconf, info, name
            return
        try:
            zeroconf.close()                                # type: ignore[attr-defined]
        except Exception:
            pass

    def _release(self) -> None:
        zeroconf, info = self._zc, self._info
        self._zc = self._info = None
        self.name = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                zeroconf.unregister_service(info)           # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            zeroconf.close()                                # type: ignore[attr-defined]
        except Exception:
            pass
