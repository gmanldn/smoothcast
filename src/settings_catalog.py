"""Shared Preferences outline for the web room (#708).

The web room can explain where each preference lives without exposing host
configuration or inventing remote controls. Keep these page and group names in
step with the desktop Preferences window.
"""
from __future__ import annotations

from html import escape
from typing import Literal, TypedDict


class HostControl(TypedDict):
    group: str
    title: str
    description: str
    kind: Literal["choice", "boolean", "number"]
    default: str | int | float | bool
    apply_timing: str

PREFERENCES = (
    ("Playback", (
        ("Picture and delivery", "Changes to encoding take effect on the next cast or transcode restart."),
        ("Colour adjustments", "Optional FFmpeg adjustments for transcoded output. A change applies to the selected film; with no film selected it becomes the default. Neutral settings preserve the source and keep direct play available."),
        ("Queue behaviour", "These options control what happens when the current film finishes."),
        ("Shared room", "Give this hosted room a recognisable name. Joining links and playback stay unchanged."),
        ("Playback alerts", "Alerts stay inside SmoothCast and never add a counter to the OS dock."),
        ("Artwork", "Shown in the preview above the scrubber."),
    )),
    ("Sound & subtitles", (
        ("Audio", "Profiles and gain are applied at the next cast or encoder restart."),
        ("Captions", "Text tracks can be sent to a Cast receiver or burned into the picture."),
    )),
    ("Appearance", (
        ("Theme", "Choose the appearance that makes the player most comfortable to read."),
        ("Updates", "Nothing is downloaded or installed automatically. These options apply on the next app launch, not during playback."),
    )),
    ("Library", (
        ("Library folders", "Folders SmoothCast indexes on this computer. Shared folders can be searched and played from every device in the house."),
    )),
)


def group_description(page: str, group: str) -> str:
    """Return the single shared description used by GTK and web Preferences."""
    for page_name, groups in PREFERENCES:
        if page_name == page:
            for group_name, description in groups:
                if group_name == group:
                    return description
            break
    raise KeyError(f"Unknown Preferences group: {page}/{group}")

HOST_CONTROLS: dict[str, HostControl] = {
    "quality": {
        "group": "Picture and delivery",
        "title": "Video quality",
        "description": "High uses more processing; Data saver reduces bandwidth and resolution.",
        "kind": "choice", "default": "balanced",
        "apply_timing": "Applies to the next cast or transcode restart.",
    },
    "rotation": {
        "group": "Picture and delivery",
        "title": "Video rotation",
        "description": "Clockwise rotation requires video transcoding.",
        "kind": "choice", "default": 0,
        "apply_timing": "Applies to the next cast or transcode restart.",
    },
    "aspect_override": {
        "group": "Picture and delivery",
        "title": "Aspect ratio",
        "description": "Stretch can distort the picture. Changes appear in the scrub preview and apply to the next cast.",
        "kind": "choice", "default": "original",
        "apply_timing": "Applies to the next cast.",
    },
    "direct": {
        "group": "Picture and delivery",
        "title": "Direct play when supported",
        "description": "Send a compatible file unchanged; sound filters and rotation may require conversion.",
        "kind": "boolean", "default": True,
        "apply_timing": "Applies to the next cast.",
    },
    "keep_streaming": {
        "group": "Picture and delivery",
        "title": "Keep casting after closing",
        "description": "Chromecast may continue playing; DLNA's local server always stops on exit.",
        "kind": "boolean", "default": True,
        "apply_timing": "Applies when SmoothCast closes.",
    },
    "auto_crop": {
        "group": "Picture and delivery",
        "title": "Crop black bars automatically",
        "description": "Detects letterboxing before a transcode and crops it; adds a few seconds to a cast start.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies to the next transcode.",
    },
    "auto_deinterlace": {
        "group": "Picture and delivery",
        "title": "Deinterlace automatically",
        "description": "Only when the film is clearly interlaced; progressive video is never touched.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies to the next transcode.",
    },
    "audio": {
        "group": "Audio",
        "title": "Sound profile",
        "description": "Original preserves the mix; Dialogue boosts speech; Night tames loud passages.",
        "kind": "choice", "default": "dialogue",
        "apply_timing": "Applies to the next cast or encoder restart.",
    },
    "audio_gain": {
        "group": "Audio",
        "title": "Dialogue loudness boost",
        "description": "Additional level in dB (0–24); effective when dialogue processing is enabled.",
        "kind": "number", "default": 6.0,
        "apply_timing": "Applies to the next cast or encoder restart.",
    },
    "audio_loudness": {
        "group": "Audio",
        "title": "Loudness normalisation",
        "description": "EBU R128 loudness with true-peak limiting — applies on the next (re)start",
        "kind": "choice", "default": "off",
        "apply_timing": "Applies to the next cast or encoder restart.",
    },
    "music_autogain": {
        "group": "Audio",
        "title": "Music autogain",
        "description": "Match tracks to -16 LUFS.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies to the next cast or restart.",
    },
    "burn_subs": {
        "group": "Captions",
        "title": "Burn subtitles into the video",
        "description": "For receivers that cannot display separate captions; needs encoding.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies to the next cast or transcode restart.",
    },
    "subtitle_style": {
        "group": "Captions",
        "title": "Subtitle appearance",
        "description": "For plain-text subtitles only; applies on the next cast or encoder restart. ASS/SSA keep their authored styling.",
        "kind": "choice", "default": "default",
        "apply_timing": "Applies to the next cast or encoder restart.",
    },
    "color_scheme": {
        "group": "Theme",
        "title": "Colour scheme", "description": "A manual choice turns off automatic day/night switching.",
        "kind": "choice", "default": "prefer-dark", "apply_timing": "Applies immediately.",
    },
    "auto_theme": {
        "group": "Theme",
        "title": "Switch theme by time of day", "description": "Use a light theme during the day and a dark theme at night.",
        "kind": "boolean", "default": False, "apply_timing": "Applies immediately.",
    },
    "accent": {
        "group": "Theme",
        "title": "Accent colour", "description": "Highlights buttons, sliders and switches. Every option keeps text readable; Default restores the original blue.",
        "kind": "choice", "default": "default", "apply_timing": "Applies immediately.",
    },
    "density": {
        "group": "Theme",
        "title": "Interface density", "description": "Scales spacing and control sizes. Long text wraps in narrow windows and under large fonts instead of being clipped.",
        "kind": "choice", "default": "comfortable", "apply_timing": "Applies immediately.",
    },
    "autonext": {
        "group": "Queue behaviour",
        "title": "Play next film automatically",
        "description": "Advance to the next item without another click.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies when the current item finishes.",
    },
    "loop": {
        "group": "Queue behaviour",
        "title": "Repeat current film",
        "description": "Repeat this film instead of advancing the queue.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies when the current item finishes.",
    },
    "loop_all": {
        "group": "Queue behaviour",
        "title": "Repeat the whole queue",
        "description": "After the final item, return to the first.",
        "kind": "boolean", "default": False,
        "apply_timing": "Applies when the last queue item finishes.",
    },
}


class HostSettingError(ValueError):
    """A rejected host setting. ``message`` is authored copy that is safe to show."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_host_setting(key: object, value: object) -> tuple[str, object]:
    """Validate a deliberately small host-only allowlist and exact value types."""
    import preference_choices  # deferred: it pulls loudness (subprocess) into core importers
    if not isinstance(key, str) or key not in HOST_CONTROLS:
        raise HostSettingError("That host setting cannot be changed from the web room")
    descriptor = HOST_CONTROLS[key]
    if descriptor["kind"] == "boolean":
        if type(value) is not bool:
            raise HostSettingError("That setting must be on or off")
        return key, value
    if descriptor["kind"] == "number":
        if type(value) not in (int, float, str):
            raise HostSettingError("That setting must be a number from 0 to 24")
        try:
            number = float(value)
        except ValueError as exc:
            raise HostSettingError("That setting must be a number from 0 to 24") from exc
        if not 0 <= number <= 24:
            raise HostSettingError("That setting must be a number from 0 to 24")
        return key, number
    choices = preference_choices.OPTIONS[key]
    for _label, choice in choices:
        if type(choice) is type(value) and choice == value:
            return key, value
        # HTML select values are strings; restore typed integer choices before
        # they reach the saved config or GTK owner.
        if type(choice) is int and isinstance(value, str) and str(choice) == value:
            return key, choice
    raise HostSettingError("Choose one of the listed options")


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
    import preference_choices  # deferred: it pulls loudness (subprocess) into core importers
    groups: dict[str, list[str]] = {}
    for key, descriptor in HOST_CONTROLS.items():
        ident = "hostSetting-" + key
        help_id = ident + "-help"
        if descriptor["kind"] == "boolean":
            control = f'<input id="{ident}" type="checkbox" aria-describedby="{help_id}">'
        elif descriptor["kind"] == "number":
            control = (f'<input id="{ident}" type="number" min="0" max="24" step="1" '
                       f'aria-describedby="{help_id}">')
        else:
            options = "".join(
                f'<option value="{escape(str(value), quote=True)}">{escape(label)}</option>'
                for label, value in preference_choices.OPTIONS[key]
            )
            control = f'<select id="{ident}" aria-describedby="{help_id}">{options}</select>'
        if descriptor["kind"] == "boolean":
            default_text = "On by default" if descriptor["default"] else "Off by default"
        elif descriptor["kind"] == "number":
            default_text = f'Default: {descriptor["default"]:g} dB'
        else:
            default_label = next(
                label for label, value in preference_choices.OPTIONS[key]
                if type(value) is type(descriptor["default"])
                and value == descriptor["default"]
            )
            default_text = "Default: " + default_label
        field_html = (
            f'<label class="host-setting" for="{ident}"><strong>{escape(descriptor["title"])}</strong>'
            f'{control}<span id="{help_id}" class="field-hint">{escape(descriptor["description"])} '
            f'{escape(default_text)} · {escape(descriptor["apply_timing"])}</span></label>'
        )
        groups.setdefault(descriptor["group"], []).append(field_html)
    sections = []
    for group, items in groups.items():
        field_html = "".join(items)
        sections.append(
            f'<section aria-label="{escape(group)} settings"><h5>{escape(group)}</h5>'
            f'<div class="host-setting-grid">{field_html}</div></section>'
        )
    return ('<section id="hostSettingsControls" class="preference-map" hidden '
            'aria-labelledby="hostSettingsHeading"><h4 id="hostSettingsHeading">Host playback and appearance</h4>'
            '<p>Changes save to the SmoothCast computer. Each setting explains when it takes effect.</p>'
            + "".join(sections)
            + '<p id="hostSettingsStatus" class="field-hint" role="status" aria-live="polite"></p></section>')


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
