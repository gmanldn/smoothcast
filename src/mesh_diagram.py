"""Connection diagram of the mesh as a self-contained SVG string (#710). GTK-free.

Nodes sit on a ring, their targets and clients orbit them, and measured links are
drawn between nodes. State is always carried by text and dash style, never colour
alone. All text is XML-escaped; the output has no scripts or external references.
"""
from __future__ import annotations

import math
from xml.sax.saxutils import escape

W, H = 640, 420
COLOURS = {"ok": "#2e9d5b", "bad": "#d33f49", "node": "#3b6fd4", "self": "#7a4fd1",
           "target": "#c98a1b", "client": "#6b7685", "text": "#1d232b"}


def _t(x: float, y: float, text: str, size: int = 11, anchor: str = "middle", weight: str = "400") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}" fill="{COLOURS["text"]}">{escape(text)}</text>')


def render(profiles, *, max_orbit: int = 6) -> str:
    """*profiles* is an iterable of ``node_profile.NodeProfile``."""
    items = list(profiles)
    if not items:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
                f'aria-label="No devices found yet">{_t(W / 2, H / 2, "No devices found yet", 14)}</svg>')
    cx, cy = W / 2, H / 2
    radius = 0 if len(items) == 1 else min(W, H) * 0.30
    pos = {}
    for i, p in enumerate(items):
        a = -math.pi / 2 + 2 * math.pi * i / len(items)
        pos[p.node_id] = (cx + radius * math.cos(a), cy + radius * math.sin(a), a)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Mesh diagram: {len(items)} device{"" if len(items) == 1 else "s"}">']
    drawn = set()
    for p in items:
        for link in p.links:
            if link.peer_kind != "node" or link.peer not in pos:
                continue
            key = tuple(sorted((p.node_id, link.peer)))
            if key in drawn:
                continue
            drawn.add(key)
            (x1, y1, _), (x2, y2, _) = pos[p.node_id], pos[link.peer]
            colour = COLOURS["ok"] if link.healthy else COLOURS["bad"]
            dash = "" if link.healthy else ' stroke-dasharray="6 4"'
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{colour}" stroke-width="2"{dash}/>')
            out.append(_t((x1 + x2) / 2, (y1 + y2) / 2 - 4, link.text, 10))
    for p in items:
        x, y, a = pos[p.node_id]
        mine = p.role == "This device"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="26" fill="{COLOURS["self" if mine else "node"]}"/>')
        out.append(_t(x, y + 4, p.role if p.role != "Node" else "Node", 10, weight="700").replace(
            f'fill="{COLOURS["text"]}"', 'fill="#fff"'))
        out.append(_t(x, y + 42, p.name, 12, weight="700"))
        sat = [("target", t) for t in p.targets] + [("client", c) for c in p.clients]
        for j, (kind, label) in enumerate(sat[:max_orbit]):
            b = a + (j - (min(len(sat), max_orbit) - 1) / 2) * 0.5
            sx, sy = x + 62 * math.cos(b), y + 62 * math.sin(b)
            out.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{sx:.1f}" y2="{sy:.1f}" stroke="{COLOURS[kind]}" '
                       f'stroke-width="1"/><circle cx="{sx:.1f}" cy="{sy:.1f}" r="6" fill="{COLOURS[kind]}"/>')
            out.append(_t(sx, sy + 17, label.split(" (")[0], 9))
        if len(sat) > max_orbit:
            out.append(_t(x, y + 56, f"+{len(sat) - max_orbit} more", 9))
    out.append("</svg>")
    return "".join(out)
