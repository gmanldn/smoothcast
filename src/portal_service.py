"""Supervisor adapter for the LAN portal (ARCH-04, #692 slice). GTK-free.

``PortalService`` satisfies ``supervisor.Service``: ``start`` builds the portal
through an injected factory (the portal serves from its constructor), ``healthy``
checks the server thread, and ``stop`` shuts it down. Not wired into the app yet.
"""
from __future__ import annotations

from typing import Callable


class PortalService:
    def __init__(self, factory: Callable[[], object]):
        self._factory = factory
        self.portal: object | None = None

    def start(self) -> None:
        if self.portal is None:
            self.portal = self._factory()

    def healthy(self) -> bool:
        thread = getattr(self.portal, "thread", None)
        return self.portal is not None and bool(thread is None or thread.is_alive())

    def stop(self) -> None:
        portal, self.portal = self.portal, None
        if portal is not None:
            portal.stop()
