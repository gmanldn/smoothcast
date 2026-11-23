"""Small GTK adapter for the validated SmoothCast peer directory."""
from __future__ import annotations

from typing import Any


def refresh_peer_links(window: Any, peers: list[dict[str, Any]], *,
                       available: bool, status: str | None = None,
                       gtk: Any | None = None) -> None:
    """Update desktop peer links only when their visible state changes."""
    box = getattr(window, "portal_peers_box", None)
    if box is None:
        return
    if gtk is None:
        from gi.repository import Gtk as gtk

    name_counts: dict[str, int] = {}
    for peer in peers:
        if isinstance(peer, dict) and isinstance(peer.get("name"), str):
            key = peer["name"].casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
    rows = []
    for peer in peers[:4]:
        if not isinstance(peer, dict) or not isinstance(peer.get("name"), str) \
                or not isinstance(peer.get("id"), str) \
                or not isinstance(peer.get("url"), str):
            continue
        name = peer["name"]
        if name_counts[name.casefold()] > 1:
            name += f" · {peer['id'][:6]}"
        rows.append((peer["url"], name, bool(peer.get("compatible"))))
    more = max(0, len(peers) - len(rows))
    if more:
        status = f"+{more} more"
    elif not rows and status is None:
        status = ("No other SmoothCast hosts found" if available else
                  "Peer discovery is unavailable on this network")
    state = (tuple(rows), available, status)
    if state == getattr(window, "_portal_peer_rows", None):
        return
    window._portal_peer_rows = state
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following
    if not rows:
        label = gtk.Label(label=status or "No other SmoothCast hosts found", xalign=0.0, wrap=True)
        label.add_css_class("section-caption")
        box.append(label)
        return
    for url, name, compatible in rows:
        if compatible:
            widget = gtk.LinkButton.new_with_label(url, name)
            widget.set_halign(gtk.Align.START)
            widget.set_tooltip_text(
                "Open this host; its own PIN is required for video upload and Cast control.")
        else:
            widget = gtk.Label(label=f"{name} (incompatible)", xalign=0.0, wrap=True)
        box.append(widget)
    if more:
        extra = gtk.Label(label=status, xalign=0.0)
        extra.add_css_class("dim-label")
        box.append(extra)
