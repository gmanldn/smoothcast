"""One registry of user actions across surfaces (issue #458, slice 1).

GTK-free and import-light. Each action lists the identifier it has on every
surface: the web room (``/api/action``), the desktop (shortcut map and app
actions), MPRIS (D-Bus methods) and the headless CLI. An empty tuple means the
surface does not offer the action; ``tests/test_action_parity.py`` keeps this
table equal to the real surfaces and lists every intentional gap, so surfaces
cannot drift apart unnoticed. Slice 1 changes no behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

SURFACES = ("web", "desktop", "mpris", "cli")


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    web: tuple[str, ...] = ()
    desktop: tuple[str, ...] = ()
    mpris: tuple[str, ...] = ()
    cli: tuple[str, ...] = ()
    envelope: bool = False  # sent as a fenced command envelope (revision + command id)

    def on(self, surface: str) -> tuple[str, ...]:
        return getattr(self, surface)


REGISTRY: tuple[Action, ...] = (
    Action("play_pause", "Play or pause", ("play_pause",), ("play_pause",),
           ("Play", "Pause", "PlayPause"), ("pause", "resume"), envelope=True),
    Action("stop", "Stop", ("stop",), ("stop-stream",), ("Stop",), ("stop",), envelope=True),
    Action("seek", "Seek", ("seek",), ("seek_back", "seek_forward"),
           ("Seek", "SetPosition"), ("seek",), envelope=True),
    Action("volume", "Volume", ("volume",), ("volume_up", "volume_down"), envelope=True),
    Action("mute", "Mute", ("mute",), ("mute",), envelope=True),
    Action("next", "Next in queue", ("next",), ("next",), ("Next",)),
    Action("previous", "Previous in queue", ("previous",), ("previous",), ("Previous",)),
    Action("queue_play", "Play a queue item now", ("queue_play",)),
    Action("queue_remove", "Remove a queue item", ("queue_remove",)),
    Action("queue_move", "Move a queue item", ("queue_move",)),
    Action("queue_next", "Play a queue item next", ("queue_next",)),
    Action("queue_clear", "Clear the queue", ("queue_clear",)),
    Action("queue_vote", "Vote for a queue item", ("queue_vote",)),
    Action("queue_add_key", "Add a search result to Up Next", ("queue_add_key",)),
    Action("music_autogain", "Normalise audio-only tracks", ("music_autogain",), envelope=True),
)

BY_ID = {action.id: action for action in REGISTRY}

# What the room API accepts: derived, never hand-listed in portal code (#458).
WEB_ACTIONS = frozenset(i for a in REGISTRY for i in a.web)
ENVELOPE_ACTIONS = frozenset(i for a in REGISTRY if a.envelope for i in a.web)


def gaps() -> list[tuple[str, str]]:
    """(action id, surface) pairs where a surface offers no identifier."""
    return [(a.id, s) for a in REGISTRY for s in SURFACES if not a.on(s)]
