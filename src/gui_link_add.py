"""Add a YouTube link from the desktop GUI into Up Next (#587).

The GUI owner reuses the room's bounded ``LinkJobs`` (one external download
per source, verified media, journal) instead of a second download path. The
GUI is a trusted local owner, not a web guest: it gets one fixed owner key that
is wrapped onto the job object here, so ``portal.py`` and mesh files are
untouched. Remote mesh routing is #589's job; this module only needs a
``LinkJobs``-shaped object and a way to enqueue a finished file.

The core is GTK-free (``Submission``/``submit``/``describe``) so it can be
tested headlessly; ``poll`` and the dialog glue stay in ``cast_session``.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import link_acquisition

# Fixed opaque owner key for the local GUI; same shape as a portal session key.
GUI_OWNER = hashlib.sha256(b"smoothcast-gui-link-owner").hexdigest()
_MARK = "_gui_link_add_wrapped"

STAGE_TEXT = {
    "pending": "Waiting to start",
    "resolving": "Looking up the video",
    "metadata": "Reading video details",
    "downloading": "Downloading",
    "verifying": "Checking the file",
    "queueing": "Adding to Up Next",
    "ready": "Added to Up Next",
    "failed": "Could not add the video",
    "cancelled": "Cancelled",
    "delivery_uncertain": "Finished; check Up Next",
}
FINAL = frozenset({"ready", "failed", "cancelled", "delivery_uncertain"})


def is_youtube(text: object) -> bool:
    """True for a single supported YouTube video link (never raises)."""
    try:
        return link_acquisition.parse_link(text).kind == "youtube"
    except link_acquisition.LinkError:
        return False


def attach(jobs, enqueue: Callable[[Path], None]) -> bool:
    """Teach *jobs* about the GUI owner once; False when there is no worker.

    ``enqueue`` must be thread-safe (the worker thread calls it)."""
    if jobs is None:
        return False
    if getattr(jobs, _MARK, False):
        return True
    active, deliver = jobs.owner_active, jobs.deliver
    jobs.owner_active = lambda key: key == GUI_OWNER or active(key)
    jobs.deliver = lambda owner, path: (enqueue(Path(path)) if owner == GUI_OWNER
                                        else deliver(owner, path))
    setattr(jobs, _MARK, True)
    return True


@dataclass(frozen=True)
class Submission:
    ok: bool
    message: str
    job_id: str = ""


def unavailable_message(jobs) -> str:
    """Say exactly what is missing; PATH/file checks only, nothing is launched."""
    row = link_acquisition.CommandProvider(("youtube",)).readiness()["youtube"]
    if row["missing"]:
        return ("YouTube needs " + ", ".join(row["missing"]) + " on this computer"
                " (see Preferences). A mesh device that has them can download for you once "
                "'Use other devices' is on in Network.")
    if jobs is None:
        return ("Turn on 'Let guests acquire YouTube links' in Preferences, then restart "
                "the room. The YouTube worker is ready on this computer.")
    return "The YouTube worker on this computer is not ready."


def submit(jobs, text: object) -> Submission:
    """Queue one YouTube link; the friendly error is safe to show."""
    if jobs is None or not jobs.capabilities().get("youtube"):
        return Submission(False, unavailable_message(jobs))
    try:
        job = jobs.submit(GUI_OWNER, text, secrets.token_hex(16))
    except link_acquisition.LinkError as exc:
        return Submission(False, exc.message)
    return Submission(True, "Adding the YouTube video to Up Next…", job)


def describe(jobs, job_id: str) -> tuple[str, bool]:
    """(progress sentence, finished?) for one job, from the privacy-safe snapshot."""
    row = next((j for j in jobs.snapshot(GUI_OWNER) if j.get("id") == job_id), None)
    if row is None:
        return "The YouTube job is no longer listed.", True
    stage = row.get("stage", "")
    text = STAGE_TEXT.get(stage, "Working")
    received, total = row.get("received"), row.get("total")
    if stage == "downloading" and isinstance(received, int) and isinstance(total, int) and total > 0:
        text += f" {min(100, received * 100 // total)}%"
    if stage in ("failed", "cancelled", "delivery_uncertain") and row.get("error"):
        text += f": {row['error']}"
    return text, stage in FINAL


# --- GTK glue (window-facing); imports stay lazy so the core above is headless ---

def add_link(window, url: str) -> None:
    """Submit *url* for the GUI owner and report progress in toasts and the console."""
    from gi.repository import GLib
    if not is_youtube(url):
        window.toast("Enter a single YouTube video link.", error=True)
        return
    jobs = getattr(getattr(getattr(window, "_portal", None), "server", None), "link_jobs", None)
    if not attach(jobs, lambda path: GLib.idle_add(lambda: window._enqueue([str(path)]) or False)):
        window.toast(unavailable_message(jobs), error=True)
        return
    result = submit(jobs, url)
    if not result.ok:
        window.toast(result.message, error=True)
        return
    window.toast(result.message)
    window._console("YouTube video accepted; adding to Up Next")
    last = [""]

    def poll():
        if getattr(window, "_closing", False):
            return False
        text, done = describe(jobs, result.job_id)
        if text != last[0]:
            last[0] = text
            window._console("YouTube: " + text)
            if done:
                window.toast(text, error=text.startswith(("Could not", "Cancelled")))
        return not done

    GLib.timeout_add_seconds(2, poll)


def _prefill(entry, clipboard, result) -> None:
    try:
        text = (clipboard.read_text_finish(result) or "").strip()
    except Exception as exc:  # noqa: BLE001 - clipboard is a convenience only
        logging.getLogger(__name__).debug("clipboard prefill skipped: %s", exc)
        return
    if is_youtube(text) and not entry.get_text():
        entry.set_text(text)
        entry.select_region(0, -1)


def show_dialog(window) -> None:
    """Ask for one YouTube link (prefilled from the clipboard) and add it."""
    from gi.repository import Adw, Gtk
    dialog = Adw.AlertDialog.new(
        "Add from YouTube",
        "Paste a YouTube video link. It is downloaded and checked, then added to "
        "Up Next. Only add media you are authorised to download.")
    entry = Gtk.Entry()
    entry.set_placeholder_text("https://www.youtube.com/watch?v=…")
    entry.update_property([Gtk.AccessibleProperty.LABEL], ["YouTube video link"])
    entry.set_activates_default(True)
    window.get_clipboard().read_text_async(None, lambda c, res: _prefill(entry, c, res))
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("add", "Add to Up Next")
    dialog.set_default_response("add")
    dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

    def answered(_dialog, response):
        text = entry.get_text().strip()
        if response == "add" and text:
            add_link(window, text)

    dialog.connect("response", answered)
    dialog.present(window)
