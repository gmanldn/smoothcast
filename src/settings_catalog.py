"""Shared Preferences outline for the web room (#708).

The web room can explain where each preference lives without exposing host
configuration or inventing remote controls. Keep these page and group names in
step with the desktop Preferences window.
"""
from __future__ import annotations

from html import escape

PREFERENCES = (
    ("Playback", (
        ("Picture and delivery", "Choose video quality, rotation, aspect ratio, direct play, and picture adjustments."),
        ("Queue behaviour", "Choose whether playback advances, repeats the current film, repeats the queue, or closes after the final film."),
        ("Shared room", "Set the room name, browser-screen access, guest link permissions, House PIN, and room port."),
        ("Playback alerts", "Choose which playback and receiver notices appear in the app."),
        ("Artwork", "Choose whether embedded cover art appears in the player."),
    )),
    ("Sound & subtitles", (
        ("Audio", "Choose a sound profile, music normalisation, dialogue level, and the selected film's audio track."),
        ("Captions", "Choose subtitle source and appearance, select a subtitle file or track, and set extra search folders."),
    )),
    ("Appearance", (
        ("Theme", "Choose colour scheme, automatic day and night switching, accent colour, and interface density."),
        ("Updates", "Choose the update channel and read-only release-check preferences."),
    )),
    ("Library", (
        ("Library folders", "Choose which folders SmoothCast indexes and shares with this room."),
    )),
)


def web_overview_html() -> str:
    """Render an escaped, read-only map of desktop Preferences for room guests."""
    sections = []
    for page, groups in PREFERENCES:
        details = "".join(
            f"<li><strong>{escape(group)}</strong><span>{escape(summary)}</span></li>"
            for group, summary in groups
        )
        sections.append(
            f'<section class="preference-map" aria-label="{escape(page)} preferences">'
            f"<h4>{escape(page)}</h4><ul>{details}</ul></section>"
        )
    return "".join(sections)
