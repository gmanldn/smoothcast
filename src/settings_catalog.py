"""Shared Preferences outline for the web room (#708).

The web room can explain where each preference lives without exposing host
configuration or inventing remote controls. Keep these page and group names in
step with the desktop Preferences window.
"""
from __future__ import annotations

from html import escape
from typing import Literal, TypedDict

import preference_choices


class HostControl(TypedDict):
    title: str
    description: str
    kind: Literal["choice", "boolean"]
    default: str | bool

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

HOST_CONTROLS: dict[str, HostControl] = {
    "color_scheme": {
        "title": "Colour scheme", "description": "Choose the host app's light or dark appearance.",
        "kind": "choice", "default": "prefer-dark",
    },
    "auto_theme": {
        "title": "Switch theme by time of day", "description": "Use light during the day and dark at night.",
        "kind": "boolean", "default": False,
    },
    "accent": {
        "title": "Accent colour", "description": "Change the highlight colour across the host app.",
        "kind": "choice", "default": "default",
    },
    "density": {
        "title": "Interface density", "description": "Change spacing and control sizes across the host app.",
        "kind": "choice", "default": "comfortable",
    },
}


def validate_host_setting(key: object, value: object) -> tuple[str, object]:
    """Validate a deliberately small host-only allowlist and exact value types."""
    if not isinstance(key, str) or key not in HOST_CONTROLS:
        raise ValueError("That host setting cannot be changed from the web room")
    descriptor = HOST_CONTROLS[key]
    if descriptor["kind"] == "boolean":
        if type(value) is not bool:
            raise ValueError("That setting must be on or off")
        return key, value
    choices = preference_choices.OPTIONS[key]
    if not any(type(choice) is type(value) and choice == value for _label, choice in choices):
        raise ValueError("Choose one of the listed options")
    return key, value


def host_setting_values(config: object) -> dict[str, object]:
    """Return only the allowlisted, validated values safe for the host UI."""
    values = config if isinstance(config, dict) else {}
    result: dict[str, object] = {}
    for key, descriptor in HOST_CONTROLS.items():
        value = values.get(key, descriptor["default"])
        try:
            _key, safe = validate_host_setting(key, value)
        except ValueError:
            safe = descriptor["default"]
        result[key] = safe
    return result


def host_controls_html() -> str:
    """Host-only controls; values arrive only after host authorization."""
    fields = []
    for key, descriptor in HOST_CONTROLS.items():
        ident = "hostSetting-" + key
        help_id = ident + "-help"
        if descriptor["kind"] == "boolean":
            control = f'<input id="{ident}" type="checkbox" aria-describedby="{help_id}">'
        else:
            options = "".join(
                f'<option value="{escape(str(value), quote=True)}">{escape(label)}</option>'
                for label, value in preference_choices.OPTIONS[key]
            )
            control = f'<select id="{ident}" aria-describedby="{help_id}">{options}</select>'
        fields.append(
            f'<label class="host-setting" for="{ident}"><strong>{escape(descriptor["title"])}</strong>'
            f'{control}<span id="{help_id}" class="field-hint">{escape(descriptor["description"])}</span></label>'
        )
    return ('<section id="hostAppearanceControls" class="preference-map" hidden '
            'aria-labelledby="hostAppearanceHeading"><h4 id="hostAppearanceHeading">Host appearance</h4>'
            '<p>Changes save to the SmoothCast computer and apply to its interface immediately.</p>'
            '<div class="host-setting-grid">' + "".join(fields) + '</div>'
            '<p id="hostSettingsStatus" class="field-hint" role="status" aria-live="polite"></p></section>')


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
    return "".join(sections) + host_controls_html()
