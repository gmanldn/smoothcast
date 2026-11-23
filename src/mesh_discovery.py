"""Adapter from the app's Cast/DLNA scan results to mesh target observations (#405).

The app already scans for receivers; this module only *reads* those lists. It
gives each receiver a stable mesh id, remembers when it was last present so
disappearance becomes ``stale`` then expires, and yields ``Discovered`` entries
for ``LocalObserver``. It never contacts a receiver. GTK-free, duck-typed on
``castctl.Device`` and ``dlna.Renderer`` so tests need no real objects.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
import hashlib
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import mesh_model as mm
import mesh_visibility as mv

CAST_PORT = 8009
_MAX = mm.MAX_TARGETS


def _short(text: str, size: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:size]


def cast_id(device: Any) -> str:
    uuid = str(getattr(device, "uuid", "") or "")
    if uuid and all(c.isalnum() or c in "-_" for c in uuid) and len(uuid) <= 64:
        return f"cast-{uuid.lower()}"
    return "cast-" + _short(f"{getattr(device, 'name', '')}|{getattr(device, 'host', '')}")


def dlna_id(renderer: Any) -> str:
    return "dlna-" + _short(str(getattr(renderer, "location", "") or
                                getattr(renderer, "key", "")))


def _probe_target(host: str, port: int) -> tuple[str, int] | None:
    return (host, port) if mm.is_lan_address(host) and 1 <= port <= 65535 else None


class DiscoveryAdapter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._known: dict[str, dict[str, Any]] = {}
        self._present: set[str] = set()
        self.updates = 0

    def update(self, cast_devices: Iterable[Any], dlna_renderers: Iterable[Any]) -> bool:
        """Record one scan result. Returns True when the set of receivers changed."""
        now = self._clock()
        entries: dict[str, dict[str, Any]] = {}
        for device in list(cast_devices or ())[:_MAX]:
            host = str(getattr(device, "host", "") or "")
            port = int(getattr(device, "port", 0) or CAST_PORT)
            entries[cast_id(device)] = {
                "kind": "cast", "name": str(getattr(device, "name", "") or "Chromecast"),
                "model": str(getattr(device, "model", "") or ""),
                "probe": _probe_target(host, port), "formats": ("video/mp4", "audio/mpeg")}
        for renderer in list(dlna_renderers or ())[:_MAX]:
            try:
                parts = urlsplit(str(getattr(renderer, "location", "") or ""))
                host = str(getattr(renderer, "host", "") or parts.hostname or "")
                port = parts.port or 80
            except ValueError:
                host, port = str(getattr(renderer, "host", "") or ""), 0
            entries[dlna_id(renderer)] = {
                "kind": "dlna", "name": str(getattr(renderer, "name", "") or "DLNA renderer"),
                "model": str(getattr(renderer, "model", "") or ""),
                "probe": _probe_target(host, port), "formats": ("video/mp4",)}
        with self._lock:
            changed = set(entries) != self._present or any(
                self._known.get(k, {}).get("name") != v["name"] for k, v in entries.items())
            for key, value in entries.items():
                self._known[key] = {**value, "last": now}
            for key in self._present - set(entries):
                if key in self._known:
                    self._known[key]["last"] = now      # it was here until this scan
            self._present = set(entries)
            for key in [k for k, v in self._known.items()
                        if k not in self._present and now - v["last"] > mv.EXPIRE_S]:
                del self._known[key]
            self.updates += 1
        return changed

    def snapshot(self) -> list[mv.Discovered]:
        """Entries for the observer: present ones count as seen right now."""
        now = self._clock()
        with self._lock:
            return [mv.Discovered(
                key, v["kind"], v["name"], now if key in self._present else v["last"],
                model=v["model"], formats=v["formats"], probe=v["probe"])
                for key, v in sorted(self._known.items())]
