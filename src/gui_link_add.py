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
    if jobs is None:
        return ("YouTube needs an isolated worker. Turn on 'Let guests acquire YouTube "
                "links' in Preferences, install yt-dlp and ffprobe, and restart the room.")
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
