"""GTK prompts for recovering or discarding a shared-room queue checkpoint."""
from __future__ import annotations

import room_checkpoint
from cast_widgets import ROOM_CHECKPOINT_FILE


def _load_adw():
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    return Adw


class RoomCheckpointController:
    """Composition replacement for RoomCheckpointUiMixin (#691); Adw is imported lazily."""

    def __init__(self, window, adw=None) -> None:
        self.w = window
        self._adw = adw

    def offer_recovery(self) -> None:
        """Ask before restoring queue paths; never resume an old cast/session."""
        w = self.w
        if getattr(getattr(w, "app", None), "selftest", False):
            return
        checkpoint = getattr(w, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        if not checkpoint.exists():
            return
        saved = room_checkpoint.load_checkpoint(checkpoint)
        if not saved.error and not saved.items and not saved.unavailable:
            return

        Adw = self._adw or _load_adw()
        revision = w._portal_observe_queue()
        handled = False

        def response(_dialog, result):
            nonlocal handled
            if handled:
                return
            handled = True
            if result not in {"recover", "discard"}:
                return
            if w._portal_observe_queue() != revision:
                w.toast("The room queue has changed. The current queue was kept.", error=True)
                return
            if result == "recover":
                self.recover()
            else:
                self.discard()

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
            dialog.present(w)
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
        dialog.present(w)


    def recover(self) -> None:
        w = self.w
        checkpoint = getattr(w, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        saved = room_checkpoint.load_checkpoint(checkpoint)
        if saved.error:
            w.toast("Shared room recovery could not be read", error=True)
            return
        if not saved.items and not saved.unavailable:
            w.toast("No saved room queue is available to recover.", error=True)
            return
        w.queue = list(saved.items)
        w._portal_queue_display_names = dict(saved.display_names)
        w.selected_index = None
        w.queue_durations = {}
        w._rebuild_queue()
        if saved.unavailable:
            w.toast(f"Recovered {len(saved.items)} item(s); skipped {saved.unavailable} unavailable item(s)")
        else:
            w.toast(f"Recovered {len(saved.items)} queued item(s)")


    def discard(self) -> None:
        w = self.w
        checkpoint = getattr(w, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        try:
            room_checkpoint.write_checkpoint(checkpoint, ())
        except (OSError, ValueError) as exc:
            w.toast("Previous room could not be discarded", error=True)
            w._console(f"Room checkpoint discard failed: {exc}")
            return
        w._room_checkpoint_last = ()
        w._room_checkpoint_names_last = ()
        w.toast("Previous room discarded")
