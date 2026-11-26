"""Guest-visible failure messages, worded once (#600).

Each message says what happened and what the guest can do next, in the room's
plain vocabulary (#599): "TV or speaker", "SmoothCast computer", "whoever runs
SmoothCast", "download". Every module that reports one of these failures to a
browser imports the constant here, so the same failure always reads the same.

HTTP status codes are chosen by the callers and are unchanged. The plain 401
``"Session expired"`` is deliberately not here: the room page maps any 401 to
its own join prompt, and API clients rely on that exact text.

Pure module: no imports, no I/O.
"""
from __future__ import annotations

SESSION_ENDED = "Your session has ended. Reload the page and join the room again."
ACCESS_REMOVED = "Your access to this room was removed. Ask whoever runs SmoothCast to let you back in."
ACCESS_REMOVED_DURING_UPLOAD = (
    "Your access to this room was removed during the upload. "
    "Ask whoever runs SmoothCast to let you back in.")
WRONG_ORIGIN = "This page was opened from an unexpected address. Open the room from its own link and try again."
YOUTUBE_OFF = ("YouTube search is unavailable on this SmoothCast computer. "
               "Try again in a moment, or add a file from your device.")
LINK_DOWNLOADS_OFF = "Downloads from links are turned off. Ask whoever runs SmoothCast to turn them on."
ARCHIVE_OFF = ("Archive link search is unavailable on this SmoothCast computer. "
              "Try again in a moment, or add a file from your device.")
LINK_DOWNLOADS_UNAVAILABLE = ("Link downloads are unavailable in this room right now. "
                            "Try again in a moment, or ask whoever runs SmoothCast.")
DOWNLOAD_CANCELLED = ("That download was stopped before it finished. "
                      "Choose the link again if you still want it.")
NO_SPACE = "There is not enough space on the SmoothCast computer. Free some space and try again."
UPLOAD_STORAGE_UNAVAILABLE = "The SmoothCast computer cannot save uploads right now. Try again in a moment."
UPLOAD_TIMED_OUT = "The upload stopped responding. Select Resume to carry on from where it stopped."
SEEK_OUT_OF_RANGE = "That point is outside the film or track. Choose an earlier point."

ALL = (SESSION_ENDED, ACCESS_REMOVED, ACCESS_REMOVED_DURING_UPLOAD, WRONG_ORIGIN, YOUTUBE_OFF,
       LINK_DOWNLOADS_OFF, ARCHIVE_OFF, LINK_DOWNLOADS_UNAVAILABLE, DOWNLOAD_CANCELLED, NO_SPACE, UPLOAD_STORAGE_UNAVAILABLE, UPLOAD_TIMED_OUT,
       SEEK_OUT_OF_RANGE)
