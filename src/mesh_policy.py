"""Who may use the protected mesh calls (ticket #404).

Default (trusted home LAN, docs/VISION.md): any private-LAN address may sync,
except revoked peers. ``strict`` additionally requires the caller to be a
current, verified member, for users who want the mesh closed to newcomers until
they have been seen by presence discovery. Public-tier calls (ping) are always
allowed. GTK-free.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

import mesh_model


class MeshPolicy:
    def __init__(self, *, strict: bool = False,
                 member_addresses: Callable[[], Iterable[str]] = lambda: (),
                 is_blocked: Callable[[str], bool] = lambda _a: False) -> None:
        self.strict = strict
        self._members = member_addresses
        self._blocked = is_blocked
        self.denials = 0

    def allow(self, source: str, kind: str) -> bool:
        host = source.rsplit(":", 1)[0] if source.count(":") == 1 else source
        ok = (mesh_model.is_lan_address(host) and not self._blocked(host)
              and (not self.strict or host in set(self._members())))
        if not ok:
            self.denials += 1
        return ok
