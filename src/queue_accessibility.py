"""GTK-free queue accessibility refresh when playback changes (#449).

The row builder owns initial labels.  During a playback handoff retained rows
must have their spoken status and CSS updated without rebuilding the ListBox.
Only the previous and current media rows can change; unchanged state is O(1).
"""
from __future__ import annotations

import queue_metadata


def sync_rows(window, gtk) -> None:
    """Synchronise current/queued row labels on the GTK owner thread."""
    previous = getattr(window, "_queue_accessibility_current", None)
    current = window.now_playing
    if previous == current:
        return
    window._queue_accessibility_current = current
    for index, path in enumerate(window.queue):
        if path != previous and path != current:
            continue
        row = window.queue_list.get_row_at_index(index)
        if row is None:
            continue
        if path == current:
            row.add_css_class("current")
            state = "Now playing"
        else:
            row.remove_css_class("current")
            state = "Queued"
        title = getattr(row, "display_title", None)
        if title is None:
            names = getattr(window, "_portal_queue_display_names", {})
            title = queue_metadata.display_title(path, window._media_cache, names.get(path))
        row.update_property(
            [gtk.AccessibleProperty.LABEL],
            [f"{title}, {index + 1} of {len(window.queue)}, {state}"],
        )
