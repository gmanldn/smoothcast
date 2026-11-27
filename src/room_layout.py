"""One layout model for the front page, shared by the GTK app and the web room (#709, #708).

Every glanceable section is declared once with its user-facing title, the web
element that renders it and the GTK builder that renders it. GTK-free.
`tests/test_room_layout.py` fails when either surface loses a section or a
section exists on one surface only, so the two stay structurally identical.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    key: str
    title: str      # the one name both surfaces show
    question: str   # what the user is asking when they look here
    web_id: str     # element id in the portal page
    gtk_builder: str  # method on the main window that builds it


# Glance order: what is playing, where, what is next, who is here.
FRONT_PAGE = (
    Section("now_playing", "Now playing", "What is playing, and where?",
            "playback", "_build_now_playing"),
    Section("targets", "Devices", "Which screen will it go to?",
            "quickCastCard", "_build_device_card"),
    Section("queue", "Up next", "What plays after this?",
            "queuePanel", "_build_queue"),
    Section("people", "People", "Who is here and what can they do?",
            "peoplePanel", "_build_portal_card"),
)
# Diagnostics are disclosed on demand, never on the front page.
DISCLOSED = (
    Section("details", "Details", "Why is it behaving like this?",
            "advancedPanel", "_build_details_card"),
)


def keys() -> tuple[str, ...]:
    return tuple(section.key for section in FRONT_PAGE + DISCLOSED)
