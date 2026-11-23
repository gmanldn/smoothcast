"""Thin, failure-proof hook that runs the mesh next to the LAN portal (#405).

Called by ``cast_portal`` when the portal starts/stops and from its 1 s activity
timer. Everything is optional: with ``mesh_enabled`` off (the default until the
Network UI ships, #403) nothing here opens a socket or starts a thread, and any
failure is swallowed so the portal, playback and GTK are never affected.
No GTK imports.
"""
from __future__ import annotations

import threading

import entry_name
import mesh_service
from version import __version__


def start(window: object, address: str) -> None:
    """(Re)start the mesh on *address* in the background; never raises."""
    try:
        settings = mesh_service.load_settings()
        stop(window)
        if not settings["enabled"]:
            return
        portal = getattr(window, "_portal", None)
        config = mesh_service.MeshConfig(
            bind_ip=address, name=getattr(portal, "name", "") or "SmoothCast",
            version=__version__, room_port=getattr(portal, "port", None),
            strict=settings["strict"], seeds=settings["seeds"])
        service = mesh_service.MeshService(config)
        entry = entry_name.EntryName(address, int(getattr(portal, "port", 0) or 0))
        window._entry_name = entry                   # type: ignore[attr-defined]
        service.primary_listeners.append(
            lambda change: entry.apply(change.new == service.node_id))
        window._mesh = service                       # type: ignore[attr-defined]
        window._mesh_sig = None                      # type: ignore[attr-defined]

        def run() -> None:
            if service.start() and portal is not None:
                try:
                    portal.server.mesh_feed = service.feed
                except Exception:
                    pass

        threading.Thread(target=run, name="smoothcast-mesh-start", daemon=True).start()
    except Exception:
        return


def stop(window: object) -> None:
    """Stop the mesh if running; never raises."""
    try:
        service = getattr(window, "_mesh", None)
        window._mesh = None                          # type: ignore[attr-defined]
        entry = getattr(window, "_entry_name", None)
        window._entry_name = None                    # type: ignore[attr-defined]
        if entry is not None:
            threading.Thread(target=entry.close, name="smoothcast-entry-stop", daemon=True).start()
        if service is None:
            return
        portal = getattr(window, "_portal", None)
        if portal is not None:
            portal.server.mesh_feed = None
        threading.Thread(target=service.stop, name="smoothcast-mesh-stop",
                         daemon=True).start()
    except Exception:
        return


def push_clients(window: object) -> None:
    """Publish the room roster and ready screens when they change; never raises."""
    service = getattr(window, "_mesh", None)
    portal = getattr(window, "_portal", None)
    if service is None or portal is None or service.state != "running":
        return
    try:
        people = portal.room.snapshot().get("participants", [])
        screens = portal.server.screens.snapshot()
        signature = (tuple((p.get("id"), p.get("name"), p.get("online")) for p in people),
                     tuple((s.get("id"), s.get("name"), s.get("ready"), s.get("state"))
                           for s in screens))
        if signature != getattr(window, "_mesh_sig", None):
            window._mesh_sig = signature             # type: ignore[attr-defined]
            service.set_clients(people, screens)
    except Exception:
        return
