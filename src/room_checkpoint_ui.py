"""GTK prompts for recovering or discarding a shared-room queue checkpoint."""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")

from gi.repository import Adw

import room_checkpoint
from cast_widgets import ROOM_CHECKPOINT_FILE


class RoomCheckpointUiMixin:
    def _offer_room_recovery(self) -> None:
        """Ask before restoring queue paths; never resume an old cast/session."""
        if getattr(getattr(self, "app", None), "selftest", False):
            return
        checkpoint = getattr(self, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        if not checkpoint.exists():
            return
        saved = room_checkpoint.load_checkpoint(checkpoint)
        if not saved.error and not saved.items and not saved.unavailable:
            return

        revision = self._portal_observe_queue()
        handled = False

        def response(_dialog, result):
            nonlocal handled
            if handled:
                return
            handled = True
            if result not in {"recover", "discard"}:
                return
            if self._portal_observe_queue() != revision:
                self.toast("The room queue has changed. The current queue was kept.", error=True)
                return
            if result == "recover":
                self._recover_room_checkpoint()
            else:
                self._discard_room_checkpoint()

        if saved.error:
            dialog = Adw.AlertDialog.new(
                "Previous room could not be read",
                "The saved queue is damaged or uses an unsupported format. Keep it for inspection, or discard it.",
            )
            dialog.add_response("keep", "Keep saved data")
            dialog.add_response("discard", "Discard previous room")
            dialog.set_default_response("keep")
            dialog.set_close_response("keep")
            dialog.connect("response", response)
            dialog.present(self)
            return
        detail = f"Recover {len(saved.items)} available queued item(s)?"
        if saved.unavailable:
            detail += f" {saved.unavailable} missing or unavailable item(s) will be skipped."
        detail += " Playback and old guest sessions will not resume."
        dialog = Adw.AlertDialog.new("Recover previous room?", detail)
        dialog.add_response("keep", "Decide later")
        dialog.add_response("discard", "Discard previous room")
        dialog.add_response("recover", "Recover queue")
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.set_response_appearance("recover", Adw.ResponseAppearance.SUGGESTED)

        dialog.connect("response", response)
        dialog.present(self)


    def _recover_room_checkpoint(self) -> None:
        checkpoint = getattr(self, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        saved = room_checkpoint.load_checkpoint(checkpoint)
        if saved.error:
            self.toast("Shared room recovery could not be read", error=True)
            return
        if not saved.items and not saved.unavailable:
            self.toast("No saved room queue is available to recover.", error=True)
            return
        self.queue = list(saved.items)
        self.selected_index = None
        self.queue_durations = {}
        self._rebuild_queue()
        if saved.unavailable:
            self.toast(f"Recovered {len(saved.items)} item(s); skipped {saved.unavailable} unavailable item(s)")
        else:
            self.toast(f"Recovered {len(saved.items)} queued item(s)")


    def _discard_room_checkpoint(self) -> None:
        checkpoint = getattr(self, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        try:
            room_checkpoint.write_checkpoint(checkpoint, ())
        except (OSError, ValueError) as exc:
            self.toast("Previous room could not be discarded", error=True)
            self._console(f"Room checkpoint discard failed: {exc}")
            return
        self._room_checkpoint_last = ()
        self.toast("Previous room discarded")
