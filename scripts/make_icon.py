#!/usr/bin/env python3
"""Regenerate SmoothCast's application artwork: ``data/cast-control.png``.

Design: dark slate squircle with a neon blue-to-violet cast glyph — signal
dot, two rounded signal arcs, and a play screen whose triangle is cut out.
A soft glow and a glassy inner edge keep it readable at dock sizes.

Rendered with PIL only (8x supersampled, then downscaled), so the committed
PNG is reproducible offline:  python3 scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

SIZE = 128
SCALE = 8
S = SIZE * SCALE
ROOT = Path(__file__).resolve().parents[1]

BG_STOPS = [(0.0, (28, 32, 52)), (0.55, (16, 18, 28)), (1.0, (9, 10, 15))]
ACCENT_STOPS = [(0.0, (53, 194, 255)), (0.45, (79, 140, 255)), (1.0, (154, 107, 255))]

SQUIRCLE_BOX = (64, 64, S - 64, S - 64)
SQUIRCLE_RADIUS = 224
CAST_CENTER = (320, 704)
DOT_RADIUS = 80
ARC_WIDTH = 56
ARC_RADII = (145, 220)
SCREEN_BOX = (544, 176, 920, 552)
SCREEN_RADIUS = 64
PLAY_TRIANGLE = [(676, 280), (676, 448), (824, 364)]


def _lerp(first: tuple, second: tuple, t: float) -> tuple:
    return tuple(round(first[i] + (second[i] - first[i]) * t) for i in range(3))


def _stops_color(stops: list, t: float) -> tuple:
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return _lerp(c0, c1, (t - t0) / (t1 - t0 or 1.0))
    return stops[-1][1]


def _diagonal_gradient(stops: list) -> Image.Image:
    lut = [_stops_color(stops, i / 2047) for i in range(2048)]
    buf = bytearray(S * S * 3)
    index = 0
    denom = 2 * (S - 1)
    for y in range(S):
        for x in range(S):
            r, g, b = lut[((x + y) * 2047) // denom]
            buf[index] = r
            buf[index + 1] = g
            buf[index + 2] = b
            index += 3
    return Image.frombytes("RGB", (S, S), bytes(buf))


def _squircle_mask() -> Image.Image:
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(SQUIRCLE_BOX, radius=SQUIRCLE_RADIUS, fill=255)
    return mask


def _glyph_masks() -> tuple[Image.Image, Image.Image]:
    """Return (silhouette, detailed) glyph masks; detailed has the play cutout."""
    silhouette = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(silhouette)
    cx, cy = CAST_CENTER
    draw.ellipse([cx - DOT_RADIUS, cy - DOT_RADIUS, cx + DOT_RADIUS, cy + DOT_RADIUS], fill=255)
    half = ARC_WIDTH // 2
    for radius in ARC_RADII:
        box_radius = radius + half
        draw.arc([cx - box_radius, cy - box_radius, cx + box_radius, cy + box_radius],
                 start=270, end=360, width=ARC_WIDTH, fill=255)
        draw.ellipse([cx - half, cy - radius - half, cx + half, cy - radius + half], fill=255)
        draw.ellipse([cx + radius - half, cy - half, cx + radius + half, cy + half], fill=255)
    draw.rounded_rectangle(SCREEN_BOX, radius=SCREEN_RADIUS, fill=255)
    detailed = silhouette.copy()
    ImageDraw.Draw(detailed).polygon(PLAY_TRIANGLE, fill=0)
    return silhouette, detailed


def build() -> Image.Image:
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    background = _squircle_mask()
    canvas.paste(_diagonal_gradient(BG_STOPS), (0, 0), background)

    silhouette, detailed = _glyph_masks()
    accent = _diagonal_gradient(ACCENT_STOPS)
    halo = ImageChops.subtract(silhouette.filter(ImageFilter.GaussianBlur(26)), silhouette)
    glow = ImageChops.multiply(halo, background)
    canvas.paste(accent, (0, 0), glow.point(lambda v: int(v * 0.5)))
    canvas.paste(accent, (0, 0), detailed)

    border = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(SQUIRCLE_BOX, radius=SQUIRCLE_RADIUS,
                                             outline=(255, 255, 255, 30), width=8)
    canvas.alpha_composite(border)

    sheen = ImageOps.invert(Image.linear_gradient("L")).point(lambda v: max(0, (v - 150) * 46 // 105))
    canvas.paste((255, 255, 255), (0, 0), ImageChops.multiply(sheen, background))
    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> int:
    destination = ROOT / "data" / "cast-control.png"
    build().save(destination)
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
