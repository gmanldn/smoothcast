"""Shared visual scales consumed by the GTK app and browser room (#708).

Semantic colours remain platform-owned: libadwaita on GTK and the accessible,
user-accent-aware palette in ``design_tokens`` on the web. Geometry and type
scales are emitted as browser custom properties and concrete GTK CSS values.
"""
from __future__ import annotations

import re

RADIUS = {"sm": 10, "md": 14, "lg": 22, "pill": 999}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 22}
TYPE = {"body": "16px", "caption": ".9em", "eyebrow": ".8em", "hero": "1.65rem"}
FONT_FAMILY = 'ui-rounded,"SF Pro Rounded","Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif'
_STEPS = sorted(v for k, v in RADIUS.items() if k != "pill")


def web_css() -> str:
    """Return root custom properties for shared geometry and type scales."""
    values = [*( (f"--sc-radius-{name}", f"{value}px") for name, value in RADIUS.items()),
              *( (f"--sc-space-{name}", f"{value}px") for name, value in SPACING.items()),
              *( (f"--sc-type-{name}", value) for name, value in TYPE.items()),
              ("--sc-font-family", FONT_FAMILY)]
    return ":root{" + "".join(f"{name}:{value};" for name, value in values) + "}"


def apply_gtk(css: bytes) -> bytes:
    """Apply shared scales to matching GTK component rules."""
    # Keep the shared hero/card vocabulary identical on GTK and in browser CSS.
    css = css.replace(b".card {\n    padding: 18px;\n    border-radius: 16px;",
                      f".card {{\n    padding: {SPACING['xl']}px;\n    border-radius: {RADIUS['md']}px;".encode())
    css = css.replace(b"font-size: 1.65em;", f"font-size: {TYPE['hero'].replace('rem', 'em')};".encode())
    css = css.replace(b"font-size: 0.8em;", f"font-size: {TYPE['eyebrow']};".encode())
    return snap_gtk_spacing(snap_gtk_radii(css))


def snap(px: int) -> int:
    """Nearest token radius; 0 stays square (flush panels), 99+ is a pill."""
    if px <= 0:
        return 0
    if px >= 99:
        return RADIUS["pill"]
    return min(_STEPS, key=lambda v: (abs(v - px), v))


def snap_gtk_radii(css: bytes) -> bytes:
    """Rewrite every ``border-radius: Npx`` in a GTK stylesheet onto the scale."""
    def one(match: re.Match[bytes]) -> bytes:
        return match.group(1) + str(snap(int(match.group(2)))).encode() + b"px"
    return re.sub(rb"(border-radius:\s*)(\d+)px", one, css)


_SPACE_STEPS = sorted(SPACING.values())


def snap_space(px: int) -> int:
    """Nearest spacing token; 0 and 1-2px hairline offsets stay as written."""
    if px <= 2:
        return px
    return min(_SPACE_STEPS, key=lambda v: (abs(v - px), v))


def snap_gtk_spacing(css: bytes) -> bytes:
    """Rewrite every ``padding``/``margin`` pixel length in a GTK stylesheet onto the scale."""
    def declaration(match: re.Match[bytes]) -> bytes:
        values = re.sub(rb"(\d+)px", lambda m: str(snap_space(int(m.group(1)))).encode() + b"px",
                        match.group(2))
        return match.group(1) + values
    return re.sub(rb"((?:padding|margin)(?:-[a-z]+)?:\s*)([^;{}]+)", declaration, css)
