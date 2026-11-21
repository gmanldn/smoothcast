"""Desktop host controls for the shared room: eject a guest, end all access."""
from __future__ import annotations

from gi.repository import Adw

import library_folders
import library_index_v2
import library_replication


class PortalHostMixin:
    def _ensure_library_indexer(self, folders=None) -> None:
        """Start the shared-library indexer once folders exist (#408)."""
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
                if current.server.library_replication is None:
                    current.server.library_replication = library_replication.Replication(indexer)

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
            self, "End guest access?",
            "All paired phones will be signed out and the six-digit PIN "
            "will change. The current film, queue and receiver keep playing.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("end", "End access")
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
        self.toast("All guests signed out. New room PIN ready; playback continues.")
