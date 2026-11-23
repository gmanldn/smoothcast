"""Design tokens for the web remote (issue #447, slice 1). GTK-free.

One table of semantic colours per scheme. The dark values are exactly the
colours the page used before, so dark mode is unchanged; the light values follow
the browser's ``prefers-color-scheme``, and ``prefers-contrast: more`` pushes
secondary text and borders to full contrast. ``contrast_ratio`` is the WCAG 2.x
formula, used by tests to keep every text pair readable.
"""
from __future__ import annotations

import accent

DARK = {
    "bg": "#101722", "card": "#1c2735", "text": "#f4f7fb", "muted": "#b7c3d0", "dim": "#8394aa",
    "accent": "#4d9de0", "on_accent": "#081522", "input": "#121b27", "border": "#718096",
    "line": "#ffffff10", "chip_line": "#ffffff12", "header_line": "#425264",
    "secondary": "#36475d", "on_secondary": "#ffffff", "danger": "#ffb4a9", "focus": "#ffd166",
    "vote": "#1c3555", "vote_line": "#4d9de066", "on_vote": "#cfe6ff", "vote_on": "#2e6fae",
    "nav": "#26364a", "nav_hover": "#364b65", "on_nav": "#e2edff",
    "scrim": "#000b", "shadow": "#0002", "avatar_text": "#08101a",
}
LIGHT = {
    "bg": "#f4f7fb", "card": "#ffffff", "text": "#101722", "muted": "#475569", "dim": "#5b6b80",
    "accent": "#1d6fb8", "on_accent": "#ffffff", "input": "#eef2f7", "border": "#64748b",
    "line": "#0f172a1a", "chip_line": "#0f172a1f", "header_line": "#cbd5e1",
    "secondary": "#e2e8f0", "on_secondary": "#1e293b", "danger": "#b42318", "focus": "#b45309",
    "vote": "#dbeafe", "vote_line": "#1d6fb866", "on_vote": "#1e3a8a", "vote_on": "#1d6fb8",
    "nav": "#e2e8f0", "nav_hover": "#cbd5e1", "on_nav": "#1e293b",
    "scrim": "#000b", "shadow": "#0f172a1a", "avatar_text": "#08101a",
}
SCHEMES = {"dark": DARK, "light": LIGHT}
# Overrides applied on top of the active scheme for prefers-contrast: more.
HIGH_CONTRAST = {"muted": "text", "dim": "text", "border": "text", "header_line": "text"}


def _vars(values: dict[str, str], scheme: str) -> str:
    result = []
    for name, value in values.items():
        css_name = name.replace("_", "-")
        if name in {"accent", "on_accent"}:
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
            candidate = colour
            for fraction in range(11):
                if contrast_ratio(candidate, values["card"]) >= 3:
                    break
                candidate = accent.mix(colour, "#000000", fraction / 10)
            variants[scheme] = {"accent": candidate, "on_accent": accent.text_on(candidate)}
        table[preset] = variants
    return table


def css() -> str:
    """Root custom properties: dark by default, light and high-contrast via media queries."""
    high_dark = {name: DARK[source] for name, source in HIGH_CONTRAST.items()}
    high_light = {name: LIGHT[source] for name, source in HIGH_CONTRAST.items()}
    return (":root{" + _vars(DARK, "dark") + "}"
            "@media(prefers-color-scheme:light){:root{" + _vars(LIGHT, "light") + "}}"
            "@media(prefers-contrast:more){:root{" + _vars(high_dark, "dark") + "}}"
            "@media(prefers-contrast:more) and (prefers-color-scheme:light){:root{" + _vars(high_light, "light") + "}}")


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
