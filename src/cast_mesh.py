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
import mesh_discovery
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
        jobs = getattr(getattr(portal, "server", None), "link_jobs", None)
        capabilities = jobs.capabilities() if jobs is not None else {}
        sources = tuple(kind for kind in ("youtube", "magnet") if capabilities.get(kind) is True)
        config = mesh_service.MeshConfig(
            bind_ip=address, name=getattr(portal, "name", "") or "SmoothCast",
            version=__version__, room_port=getattr(portal, "port", None),
            strict=settings["strict"], seeds=settings["seeds"],
            link_acquisition_sources=sources,
            link_activity=getattr(jobs, "snapshot", lambda: []))
        adapter = mesh_discovery.DiscoveryAdapter()
        config.discovery = adapter.snapshot
        window._mesh_discovery = adapter             # type: ignore[attr-defined]
        window._mesh_scan_sig = None                 # type: ignore[attr-defined]
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
                    # A delayed startup must not attach a replaced mesh service.
                    if getattr(window, "_mesh", None) is service:
                        portal.server.mesh_feed = service.feed
                        portal.server.mesh_acquisition_activity = service.acquisition_activity
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
            portal.server.mesh_acquisition_activity = None
        threading.Thread(target=service.stop, name="smoothcast-mesh-stop",
                         daemon=True).start()
    except Exception:
        return


def refresh_view(window: object) -> None:
    """Refresh the Network popover (GTK thread); never raises."""
    try:
        import mesh_ui
        mesh_ui.refresh(window)
    except Exception:
        return


def push_clients(window: object) -> None:
    """Publish the room roster and ready screens when they change; never raises."""
    refresh_view(window)
    service = getattr(window, "_mesh", None)
    portal = getattr(window, "_portal", None)
    if service is None or portal is None or service.state != "running":
        return
    try:
        _feed_discovery(window, service)
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


def _feed_discovery(window: object, service: object) -> None:
    """Hand the app's latest Cast/DLNA scan lists to the mesh when they change."""
    adapter = getattr(window, "_mesh_discovery", None)
    if adapter is None:
        return
    cast = list(getattr(window, "devices", None) or [])
    dlna = list(getattr(window, "dlna_devices", None) or [])
    signature = (tuple(mesh_discovery.cast_id(d) + str(getattr(d, "name", "")) for d in cast),
                 tuple(mesh_discovery.dlna_id(d) + str(getattr(d, "name", "")) for d in dlna))
    if signature != getattr(window, "_mesh_scan_sig", None):
        window._mesh_scan_sig = signature            # type: ignore[attr-defined]
        adapter.update(cast, dlna)
        service.discovery_changed()                  # type: ignore[attr-defined]
