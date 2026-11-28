"""Design tokens for the web remote (issue #447, slice 1). GTK-free.

One branded semantic palette per scheme. The light values follow
the browser's ``prefers-color-scheme``, and ``prefers-contrast: more`` pushes
secondary text and borders to full contrast. ``contrast_ratio`` is the WCAG 2.x
formula, used by tests to keep every text pair readable.
"""
from __future__ import annotations

import accent

DARK = {
    "bg": "#0B1220",
    "card": "#151F30",
    "text": "#F4F7FB",
    "muted": "#B7C4D6",
    "dim": "#9AACC3",
    "accent": "#76C7FF",
    "on_accent": "#0B1220",
    "input": "#101A2A",
    "border": "#74859E",
    "line": "#FFFFFF14",
    "chip_line": "#FFFFFF18",
    "header_line": "#40516A",
    "secondary": "#293B52",
    "on_secondary": "#F4F7FB",
    "danger": "#FFB4A9",
    "focus": "#FFD166",
    "vote": "#203951",
    "vote_line": "#76C7FF66",
    "on_vote": "#D9EDFF",
    "vote_on": "#245F93",
    "nav": "#202F44",
    "nav_hover": "#30445F",
    "on_nav": "#F4F7FB",
    "qr_paper": "#FFFFFF",
    "media_surface": "#0B1220",
    "media_text": "#F4F7FB",
    "scrim": "#000B",
    "shadow": "#0002",
    "avatar_text": "#08101A",
}
LIGHT = {
    "bg": "#F4F7FB",
    "card": "#FFFFFF",
    "text": "#0B1220",
    "muted": "#475569",
    "dim": "#52637B",
    "accent": "#126397",
    "on_accent": "#FFFFFF",
    "input": "#EAF0F6",
    "border": "#64748B",
    "line": "#0F172A1A",
    "chip_line": "#0F172A1F",
    "header_line": "#CBD5E1",
    "secondary": "#E1E9F2",
    "on_secondary": "#18263A",
    "danger": "#B42318",
    "focus": "#9A490A",
    "vote": "#DBEAFE",
    "vote_line": "#12639766",
    "on_vote": "#153D62",
    "vote_on": "#126397",
    "nav": "#E1E9F2",
    "nav_hover": "#CBD9E8",
    "on_nav": "#18263A",
    "qr_paper": "#FFFFFF",
    "media_surface": "#0B1220",
    "media_text": "#F4F7FB",
    "scrim": "#000B",
    "shadow": "#0F172A1A",
    "avatar_text": "#08101A",
}
SCHEMES = {"dark": DARK, "light": LIGHT}
# Overrides applied on top of the active scheme for prefers-contrast: more.
HIGH_CONTRAST = {"muted": "text", "dim": "text", "border": "text", "header_line": "text"}
# forced-colors: active (Windows contrast themes) hands colour choice to the user's
# palette, so every surface/text pair maps to a CSS system colour pair that the OS
# guarantees readable. QR paper, scrim, shadow and avatar text stay literal.
FORCED = {
    "bg": "Canvas", "card": "Canvas", "text": "CanvasText", "muted": "CanvasText",
    "dim": "CanvasText", "accent": "Highlight", "on_accent": "HighlightText",
    "input": "Field", "border": "ButtonBorder", "line": "ButtonBorder",
    "chip_line": "ButtonBorder", "header_line": "ButtonBorder",
    "secondary": "ButtonFace", "on_secondary": "ButtonText", "danger": "CanvasText",
    "focus": "Highlight", "vote": "Canvas", "vote_line": "ButtonBorder",
    "on_vote": "CanvasText", "vote_on": "Highlight", "nav": "ButtonFace",
    "nav_hover": "ButtonFace", "on_nav": "ButtonText",
    "media_surface": "Canvas", "media_text": "CanvasText",
}


def _vars(values: dict[str, str], scheme: str | None) -> str:
    result = []
    for name, value in values.items():
        css_name = name.replace("_", "-")
        if scheme and name in {"accent", "on_accent"}:
            value = f"var(--sc-user-{css_name}-{scheme}, {value})"
        result.append(f"--{css_name}:{value};")
    return "".join(result)


def web_accents() -> dict[str, dict[str, dict[str, str]]]:
    """Only reviewed preset IDs and readable colours; no untrusted CSS/JS."""
    table: dict[str, dict[str, dict[str, str]]] = {}
    for preset, _label, _colour in accent.PRESETS:
        if preset == accent.DEFAULT_ID:
            table[preset] = {
                scheme: {"accent": values["accent"], "on_accent": values["on_accent"]}
                for scheme, values in SCHEMES.items()
            }
            continue
        colour = accent.accent_hex(preset)
        variants = {}
        for scheme, values in SCHEMES.items():
            # Accent is also used for normal-size links, not just controls.
            # Preserve the preset where possible, but meet AA on every surface.
            target = "#ffffff" if scheme == "dark" else "#000000"
            for fraction in range(101):
                candidate = accent.mix(colour, target, fraction / 100)
                on_accent = accent.text_on(candidate)
                if contrast_ratio(candidate, on_accent) < 4.5:
                    on_accent = max(("#000000", "#ffffff"),
                                    key=lambda text: contrast_ratio(candidate, text))
                if (contrast_ratio(candidate, on_accent) >= 4.5
                        and all(contrast_ratio(candidate, values[surface]) >= 4.5
                                for surface in ("bg", "card", "input"))):
                    break
            variants[scheme] = {"accent": candidate, "on_accent": on_accent}
        table[preset] = variants
    return table



# The portal embeds the token stylesheet before its base component rules.
# Scope the Home treatment tightly so it also works in the shared stylesheet.
_HOME_CSS = """
#dashboard #homePanel #playback {
    padding: clamp(16px, 4vw, 32px);
    border: 1px solid var(--header-line);
    border-radius: 24px;
    background-color: var(--card);
}
#dashboard #homePanel #playback #title.big {
    margin-block: 0.45em 0.2em;
    font-size: clamp(1.65rem, 4vw, 2.75rem);
    line-height: 1.08;
    letter-spacing: -0.035em;
    text-wrap: balance;
}
#dashboard #homePanel #playback .row {
    font-variant-numeric: tabular-nums;
}
#dashboard #homePanel #playback .actions button[data-action="play_pause"] {
    min-height: 48px;
    font-weight: 750;
}
#dashboard #homePanel #quickCastCard {
    padding: 16px clamp(14px, 4vw, 24px);
    border: 1px solid var(--header-line);
    border-radius: 18px;
}
#dashboard #homePanel #glance {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
}
#dashboard #homePanel #glance .glance-tile {
    border-radius: 14px;
    background: var(--input);
}
#dashboard #homePanel .home-actions .home-action {
    min-height: 48px;
    border-radius: 14px;
    background: var(--card);
}
#dashboard #homePanel .home-actions .home-action:hover {
    border-color: var(--accent);
    background: var(--input);
}
@media (max-width: 480px) {
    #dashboard #homePanel #glance {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    #dashboard #homePanel #glance .glance-tile:first-child {
        grid-column: 1 / -1;
    }
}
@media (prefers-contrast: no-preference) and (forced-colors: none) {
    #dashboard #homePanel #playback {
        background-image: radial-gradient(ellipse at 96% 0%,
            color-mix(in srgb, var(--accent) 13%, transparent), transparent 64%);
        box-shadow: 0 16px 48px var(--shadow);
    }
}
@media (prefers-contrast: more), (forced-colors: active) {
    #dashboard #homePanel #playback {
        background-image: none;
    }
}
"""


def css() -> str:
    """Shared custom properties and token-based room Home styles."""
    high_dark = {name: DARK[source] for name, source in HIGH_CONTRAST.items()}
    high_light = {name: LIGHT[source] for name, source in HIGH_CONTRAST.items()}
    return (":root{" + _vars(DARK, "dark") + "}"
            "@media(prefers-color-scheme:light){:root{" + _vars(LIGHT, "light") + "}}"
            "@media(prefers-contrast:more){:root{" + _vars(high_dark, "dark") + "}}"
            "@media(prefers-contrast:more) and (prefers-color-scheme:light){:root{" + _vars(high_light, "light") + "}}"
            + _HOME_CSS
            + "@media(forced-colors:active){:root{" + _vars(FORCED, None) + "}}")


def _channel(value: int) -> float:
    s = value / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast of two opaque ``#rrggbb`` colours (alpha digits are ignored)."""
    a, b = luminance(foreground), luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
