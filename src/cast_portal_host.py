"""Desktop host controls for the shared room: eject a guest, end all access."""
from __future__ import annotations

from gi.repository import Adw, Gtk

import error_log
import library_folders
import shutdown_plan
import peer_discovery_ui
import portal_uploads
from cast_widgets import Async


class PortalHostMixin:
    def _portal_timing(self) -> tuple[float | None, float]:
        """Position and total runtime for guests; external media uses the receiver's own length."""
        position = self.tracker.value()
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        runtime = getattr(self, "_external_runtime", None) if self.external else None
        if runtime and not duration:
            position, duration = (position or runtime[0]), runtime[1]
        return position, duration

    def _shutdown_plan(self):
        """The one ordered, deadline-bounded shutdown plan for this window (#465)."""
        plan = self.__dict__.get("_shutdown_plan_obj")
        if plan is None:
            plan = shutdown_plan.ShutdownPlan(log=error_log.log)
            self._shutdown_plan_obj = plan
        return plan

    def _finish_shutdown(self) -> None:
        """Record that this exit completed; the next start counts it as clean."""
        plan = self._shutdown_plan()
        report = plan.report()
        if not report["within_budget"]:
            error_log.log(f"Shutdown took {report['total_ms']:.0f} ms (budget "
                          f"{report['budget_ms']:.0f} ms); slow steps: {', '.join(report['overruns']) or 'none'}")
        shutdown_plan.ShutdownLedger().end(report)

    def _stop_house_services(self) -> None:
        """Stop the library indexer and mesh-library threads; safe to call twice."""
        mesh, self._mesh_library = getattr(self, "_mesh_library", None), None
        indexer, self._library_indexer = getattr(self, "_library_indexer", None), None
        if mesh is not None:
            mesh.stop()
        if indexer is not None:
            indexer.stop(0.3)
        import fingerprint
        fingerprint.KEYS.close()

    def _ensure_library_indexer(self, folders=None) -> None:
        """Start the shared-library indexer once folders exist (#408)."""
        import library_index_v2          # sqlite + search stack: only when folders exist (#463)
        import library_replication
        if not self.cfg.get("library_indexer", True):
            return
        folders = library_folders.load(self.cfg) if folders is None else folders
        indexer = getattr(self, "_library_indexer", None)
        if indexer is None and folders:
            try:
                indexer = library_index_v2.LibraryIndexer(
                    busy=lambda: bool(getattr(self, "session", None) and self.busy))
            except Exception:
                return
            self._library_indexer = indexer
            indexer.start()
        if indexer is not None:
            indexer.set_folders(folders)
            current = getattr(self, "_portal", None)
            if current is not None:
                current.server.library_search = indexer.search
                self._ensure_mesh_library(indexer, current)
                if current.server.library_replication is None:
                    current.server.library_replication = library_replication.Replication(indexer)

    def _ensure_mesh_library(self, indexer, current) -> None:
        """House-wide search: replicas of peers' shared libraries (#411, #412)."""
        import mesh_library
        mesh = getattr(self, "_mesh_library", None)
        if mesh is None:
            try:
                mesh = mesh_library.MeshLibrary(
                    indexer, busy=lambda: bool(getattr(self, "session", None) and self.busy))
            except Exception:
                return
            self._mesh_library = mesh
            mesh.start()
        current.server.library_search = mesh.search_service.search
        current.server.library_search_stream = mesh.search_service.stream
        current.server.mesh_files = mesh.files
        current.server.library_browser = mesh

    def on_library_folders_changed(self, folders) -> None:
        self._ensure_library_indexer(folders)

    def _portal_revoke_selected(self, *_args) -> None:
        """Only the local desktop host may eject an identified room guest."""
        current = getattr(self, "_portal", None)
        ids = getattr(self, "portal_guest_ids", ())
        dropdown = getattr(self, "portal_guest_dropdown", None)
        selected = dropdown.get_selected() if dropdown is not None else len(ids)
        if current is None or selected >= len(ids):
            self.toast("No guest is selected", error=True)
            return
        removed = current.revoke_guest(ids[selected])
        if removed:
            self.toast("Guest access revoked; playback continues")
            self.portal_guest_ids = ()  # Rebuild roster on the next refresh.
            self._refresh_portal_activity()
        else:
            self.toast("That guest has already left")

    def _portal_confirm_end_access(self, *_args) -> None:
        """Confirmation prevents accidental all-room ejection."""
        if getattr(self, "_portal", None) is None:
            self.toast("The shared room is not running", error=True)
            return
        dialog = Adw.MessageDialog.new(
            self, "Sign everyone out?",
            "Every connected browser will be signed out and the room PIN "
            "will change. The current film, queue and receiver keep playing.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("end", "Sign out")
        dialog.set_response_appearance("end", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response", lambda _dialog, response:
            self._portal_end_guest_access() if response == "end" else None)
        dialog.present()

    def _portal_end_guest_access(self) -> None:
        current = getattr(self, "_portal", None)
        if current is None:
            return
        self.portal_pin_label.set_text(current.end_guest_access())
        self.portal_guest_ids = ()
        self._refresh_portal_activity()
        self.toast("Everyone signed out. New room PIN ready; playback continues.")

    def _refresh_portal_activity(self) -> bool:
        """Show what LAN clients are sending or casting, refreshed every second."""
        label = getattr(self, "portal_activity_label", None)
        if label is None or getattr(self, "_closing", False):
            self._portal_activity_timer = None
            return False
        uploads = getattr(getattr(self, "_portal", None), "uploads", None)
        try:
            activity = uploads.snapshot() if uploads is not None else []
        except Exception:
            activity = []
        room = getattr(getattr(getattr(self, "_portal", None), "server", None), "room", None)
        participants = room.snapshot().get("participants", []) if room is not None else []
        names = [person["name"] for person in participants if isinstance(person, dict)
                 and isinstance(person.get("name"), str)]
        roster = ", ".join(names[:4])
        if len(names) > 4:
            roster += f", +{len(names) - 4} more"
        ids = tuple(person["id"] for person in participants
                    if isinstance(person, dict) and isinstance(person.get("id"), str))
        if hasattr(self, "portal_guest_dropdown") and ids != getattr(self, "portal_guest_ids", ()):
            prior = getattr(self, "portal_guest_ids", ())
            selected = self.portal_guest_dropdown.get_selected()
            chosen = prior[selected] if selected < len(prior) else None
            labels = [str(person.get("name", "Guest")) for person in participants
                      if isinstance(person, dict) and isinstance(person.get("id"), str)]
            self.portal_guest_ids = ids
            self.portal_guest_dropdown.set_model(
                Gtk.StringList.new(labels if labels else ["No guests connected"]))
            self.portal_guest_dropdown.set_selected(
                ids.index(chosen) if chosen in ids else 0)
            self.portal_guest_dropdown.set_sensitive(bool(ids))
            self.portal_revoke_button.set_sensitive(bool(ids))
        summary = portal_uploads.format_portal_activity(activity)
        presence = f"In room: {roster}" if roster else "No guests connected"
        screens = getattr(getattr(self._portal, "server", None), "screens", None)
        try:
            screen_rows = screens.snapshot() if screens is not None else []
        except Exception:
            screen_rows = []
        ready = [f"{row['name']} ({row['state']})" for row in screen_rows[:3]
                 if isinstance(row, dict) and row.get("ready")]
        shown = f" · Screens: {', '.join(ready)}" if ready else ""
        label.set_text(f"{presence} · {summary}{shown}")
        peers = getattr(getattr(self, "_portal", None), "peers", None)
        peer_list = peers.snapshot() if peers is not None else []
        available = getattr(getattr(self, "_portal", None),
                            "peer_discovery_available", False)
        peer_discovery_ui.refresh_peer_links(self, peer_list, available=available)
        if getattr(self, "_portal", None) is not None:
            self._portal.server.nodes_provider = lambda: peer_list
        mesh = getattr(self, "_mesh_library", None)
        if mesh is not None:
            Async.run(lambda: mesh.observe_peers(peer_list), domain="background")
        self._reconcile_portal_casts()
        import cast_mesh
        cast_mesh.push_clients(self)
        return True
