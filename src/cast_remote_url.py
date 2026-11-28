"""Casting a remote URL or YouTube link straight to the receiver."""
from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk
import castctl
import gui_link_add
import playback_state
import url_control
from cast_widgets import Async


class RemoteUrlCastMixin:
    def _cast_remote_url(self, value: str) -> None:
        # External URLs use Cast, not DLNA.
        if self._dlna_renderer() is not None:
            self.toast("Open URL currently requires a Google Cast target; choose Cast or open a local film", error=True)
            return
        try:
            url = url_control.validate_media_url(value)
        except ValueError:
            self.toast("Enter a valid HTTP or HTTPS media URL and try again.", error=True)
            return
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        device = self._device()
        generation = getattr(self, "_remote_url_cast_generation", 0) + 1
        self._remote_url_cast_generation = generation

        def current() -> bool:
            return (not getattr(self, "_closing", False)
                    and getattr(self, "_remote_url_cast_generation", None) == generation
                    and self._device() == device)

        # The old session keeps serving the receiver until the replacement is
        # confirmed: a rejected or unconfirmed LOAD must not strand the TV.
        previous = self.session
        self.busy = True
        self._refresh_controls()
        self.toast(f"Opening remote stream on {device}…")

        def work():
            # Don't send remote URLs through local-file ffprobe.
            ok, message = castctl.command(device, "cast", "--no-subs", url, timeout=60)
            if not ok and message == castctl.COMMAND_TIMEOUT_MESSAGE:
                # Ambiguous: reconcile observed content before deciding.
                ok = playback_state.url_cast_matches(castctl.info(device), url)
            if ok and previous is not None and current():
                previous.stop(device, send_stop=False)  # never a speculative remote Stop
            return ok, message

        def done(result):
            if not current():
                return
            ok, message = result
            self.busy = False
            if not ok:
                self._cast_failed(message or "Remote cast failed")
                return
            if self.session is previous:
                self.session = None
            self._stop_monitor()
            # Release local playback after handoff to prevent overlapping audio.
            self._unload_local_video()
            self.local_playback.stop()
            self.media = None
            self.now_playing = None
            self.external = True
            self._url_cast_url = url
            self._url_cast_seen = False
            self.tracker.clear()
            self._external_display_clock = None
            self._external_runtime = None
            self.np_title.set_text("Remote stream")
            self.toast(f"Remote stream sent to {device}")
            self._console(f"Remote stream sent to {device}")
            self._refresh_controls()
            self._poll_device()

        def failed(message):
            if current():
                self._cast_failed(message)

        Async.run(work, done=done, failed=failed, domain="transport")

    def _open_url(self) -> None:
        dialog = Adw.AlertDialog.new("Open URL", "Paste a stream URL")
        entry = Gtk.Entry()
        entry.set_placeholder_text("https://...")
        entry.update_property([Gtk.AccessibleProperty.LABEL], ["Stream URL"])
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("open", "Open")
        dialog.set_default_response("open")
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        def on_resp(d, r):
            if r == "open":
                url = entry.get_text().strip()
                if url and gui_link_add.is_youtube(url):
                    self._add_youtube_link(url)    # a page, not media: acquire into Up Next
                elif url:
                    self._cast_remote_url(url)
        dialog.connect("response", on_resp)
        dialog.present(self)

    def _add_youtube(self) -> None:
        gui_link_add.show_dialog(self)

    def _add_youtube_link(self, url: str) -> None:
        gui_link_add.add_link(self, url)
