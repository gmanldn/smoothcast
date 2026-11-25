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
import mesh_acquisition_app
import mesh_discovery
import mesh_service
from version import __version__


def start(window: object, address: str) -> None:
    """(Re)start the mesh on *address* in the background; never raises."""
    try:
        window._mesh_address = address               # type: ignore[attr-defined]
        settings = mesh_service.load_settings()
        stop(window)
        if not settings["enabled"]:
            return
        portal = getattr(window, "_portal", None)
        jobs = getattr(getattr(portal, "server", None), "link_jobs", None)
        if jobs is None and settings.get("remote_acquisition"):
            # No local worker here: still let mesh workers serve the owner-enabled kinds.
            jobs = mesh_acquisition_app.ensure_jobs(portal, getattr(window, "cfg", None) or {})
        capabilities = jobs.capabilities() if jobs is not None else {}
        sources = tuple(kind for kind in ("youtube", "magnet") if capabilities.get(kind) is True)
        remote = None
        if settings.get("remote_acquisition") or settings.get("accept_acquisition"):
            remote = _remote_acquisition(settings, address, jobs)
        config = mesh_service.MeshConfig(
            bind_ip=address, name=getattr(portal, "name", "") or "SmoothCast",
            version=__version__, room_port=getattr(portal, "port", None),
            strict=settings["strict"], seeds=settings["seeds"],
            link_acquisition_sources=sources,
            link_activity=(lambda: remote.activity(jobs.snapshot() if jobs is not None else []))
            if remote is not None else getattr(jobs, "snapshot", lambda: []),
            acquisition_worker=getattr(remote, "worker", None),
            acquisition_accept=lambda: bool(mesh_service.load_settings()["accept_acquisition"]),
            acquisition_attach=remote.attach if remote is not None else None)
        adapter = mesh_discovery.DiscoveryAdapter()
        config.discovery = adapter.snapshot
        window._mesh_discovery = adapter             # type: ignore[attr-defined]
        window._mesh_scan_sig = None                 # type: ignore[attr-defined]
        service = mesh_service.MeshService(config)
        window._mesh_remote = remote                 # type: ignore[attr-defined]
        if remote is not None and jobs is not None and settings.get("remote_acquisition"):
            # Mesh workers become one more provider for the room's own LinkJobs.
            remote.original_provider = jobs.provider
            jobs.provider = mesh_acquisition_app.CompositeProvider(jobs.provider, remote)
            remote.jobs = jobs
        entry = getattr(window, "_entry_name", None)
        if entry is None:
            # No app-owned stable address: create one and remember we must release it.
            entry = entry_name.EntryName(address, int(getattr(portal, "port", 0) or 0))
            window._mesh_entry_owned = True       # type: ignore[attr-defined]
        else:
            window._mesh_entry_owned = False      # type: ignore[attr-defined]
        window._entry_name = entry                # type: ignore[attr-defined]
        service.primary_listeners.append(
            lambda change: entry.apply(change.new == service.node_id))
        window._mesh = service                       # type: ignore[attr-defined]
        window._mesh_sig = None                      # type: ignore[attr-defined]

        def run() -> None:
            started = service.start()
            if started and remote is not None:
                try:
                    remote.reconcile()  # stop-or-confirm workers a previous run may have left running
                except Exception:
                    pass
            if started and portal is not None:
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


ACQUISITION_KEYS = {"remote_acquisition": "mesh_remote_acquisition",
                    "accept_acquisition": "mesh_accept_acquisition"}


def set_acquisition(window: object, name: str, value: object, *, save=None, flush=None) -> bool:
    """Persist one remote-acquisition opt-in and restart the mesh so it takes effect.

    Both switches are off by default and only ever flipped by an explicit user
    action in the Network popover. Never raises; returns whether it was applied.
    """
    key = ACQUISITION_KEYS.get(name) if isinstance(name, str) else None
    cfg = getattr(window, "cfg", None)
    if key is None or type(value) is not bool or not isinstance(cfg, dict):
        return False
    try:
        if save is None or flush is None:
            import config_persistence
            save, flush = save or config_persistence.save_config, flush or config_persistence.flush_config
        cfg[key] = value
        save(cfg)
        flush()  # start() reads the file, so it must be on disk first
        address = getattr(window, "_mesh_address", None)
        if address:
            start(window, address)
        return True
    except Exception:
        return False


def _remote_acquisition(settings: dict, address: str, jobs: object):
    """Build the opt-in remote acquisition glue; None when it cannot be made safely."""
    try:
        import pathlib
        local = getattr(jobs, "provider", None)
        local = getattr(local, "local", local)  # never wrap a wrapper
        base = pathlib.Path(mesh_service.config_path().parent) / "mesh-acquisition"
        return mesh_acquisition_app.RemoteAcquisition(
            base, bind_ip=address, local_provider=local,
            use_workers=lambda: bool(mesh_service.load_settings()["remote_acquisition"]),
            accept_work=lambda: bool(mesh_service.load_settings()["accept_acquisition"]))
    except Exception:
        return None


def stop(window: object) -> None:
    """Stop the mesh if running; never raises."""
    try:
        service = getattr(window, "_mesh", None)
        window._mesh = None                          # type: ignore[attr-defined]
        remote = getattr(window, "_mesh_remote", None)
        window._mesh_remote = None                   # type: ignore[attr-defined]
        if remote is not None:
            if getattr(remote, "jobs", None) is not None and getattr(remote, "original_provider", None):
                remote.jobs.provider = remote.original_provider
            threading.Thread(target=remote.close, name="smoothcast-acq-stop", daemon=True).start()
        entry = getattr(window, "_entry_name", None)
        owned = bool(getattr(window, "_mesh_entry_owned", False))
        window._mesh_entry_owned = False             # type: ignore[attr-defined]
        if owned:
            # Only release an address this hook created; an app-owned entry
            # survives mesh restarts and is closed by the portal.
            window._entry_name = None                # type: ignore[attr-defined]
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
