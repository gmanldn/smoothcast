"""One registry of user actions across surfaces (issue #458).

GTK-free and import-light. Each action is defined once with its id, label,
accessible description, icon, capability predicate and the permission needed to
invoke it, plus the identifier it has on every surface: the web room
(``/api/action``), the desktop (shortcut map and app actions), MPRIS (D-Bus
methods) and the headless CLI. An empty tuple means the surface does not offer
the action; ``tests/test_action_parity.py`` keeps this table equal to the real
surfaces and lists every intentional gap, so surfaces cannot drift apart
unnoticed.

``capability`` names the pure predicate in :mod:`action_state` that decides
whether the action is available right now (empty when the room or queue decides
instead). ``permission`` is the minimum room role allowed to invoke the action;
every action today is open to any joined participant.
"""
from __future__ import annotations

from dataclasses import dataclass

SURFACES = ("web", "desktop", "mpris", "cli")

# Room roles, weakest first. Only ``participant`` is used today; the field exists
# so a future host-only action is declared here rather than in each surface.
PARTICIPANT = "participant"


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    description: str
    icon: str
    web: tuple[str, ...] = ()
    desktop: tuple[str, ...] = ()
    mpris: tuple[str, ...] = ()
    cli: tuple[str, ...] = ()
    capability: str = ""  # action_state predicate that gates availability, "" when none
    permission: str = PARTICIPANT  # minimum room role allowed to invoke
    envelope: bool = False  # sent as a fenced command envelope (revision + command id)

    def on(self, surface: str) -> tuple[str, ...]:
        return getattr(self, surface)


REGISTRY: tuple[Action, ...] = (
    Action("play_pause", "Play or pause", "Play or pause playback on the chosen receiver.",
           "media-playback-start-symbolic", web=("play_pause",), desktop=("play_pause",),
           mpris=("Play", "Pause", "PlayPause"), cli=("pause", "resume"),
           capability="can_play_pause", envelope=True),
    Action("stop", "Stop", "Stop playback on the chosen receiver.",
           "media-playback-stop-symbolic", web=("stop",), desktop=("stop-stream",),
           mpris=("Stop",), cli=("stop",), capability="can_stop", envelope=True),
    Action("seek", "Seek", "Seek within the current stream by a relative amount.",
           "media-seek-forward-symbolic", web=("seek",), desktop=("seek_back", "seek_forward"),
           mpris=("Seek", "SetPosition"), cli=("seek",), capability="can_seek", envelope=True),
    Action("volume", "Volume", "Change the receiver volume.",
           "audio-volume-high-symbolic", web=("volume",), desktop=("volume_up", "volume_down"),
           capability="can_volume", envelope=True),
    Action("mute", "Mute", "Mute or unmute the receiver.",
           "audio-volume-muted-symbolic", web=("mute",), desktop=("mute",),
           capability="can_volume", envelope=True),
    Action("next", "Next in queue", "Play the next item in Up Next.",
           "media-skip-forward-symbolic", web=("next",), desktop=("next",), mpris=("Next",)),
    Action("previous", "Previous in queue", "Play the previous item in Up Next.",
           "media-skip-backward-symbolic", web=("previous",), desktop=("previous",),
           mpris=("Previous",)),
    Action("queue_play", "Play a queue item now", "Play a specific Up Next item now.",
           "media-playback-start-symbolic", web=("queue_play",)),
    Action("queue_remove", "Remove a queue item", "Remove an item from Up Next.",
           "edit-delete-symbolic", web=("queue_remove",)),
    Action("queue_move", "Move a queue item", "Reorder an item in Up Next.",
           "view-list-symbolic", web=("queue_move",)),
    Action("queue_next", "Play a queue item next", "Play an Up Next item after the current one.",
           "go-next-symbolic", web=("queue_next",)),
    Action("queue_clear", "Clear the queue", "Clear every item from Up Next.",
           "edit-clear-all-symbolic", web=("queue_clear",)),
    Action("queue_vote", "Vote for a queue item", "Vote to keep or skip an Up Next item.",
           "emblem-ok-symbolic", web=("queue_vote",)),
    Action("queue_add_key", "Add a search result to Up Next",
           "Add a search result to Up Next.", "list-add-symbolic", web=("queue_add_key",)),
    Action("music_autogain", "Normalise audio-only tracks",
           "Normalise the loudness of audio-only tracks.",
           "audio-volume-high-symbolic", web=("music_autogain",), envelope=True),
)

BY_ID = {action.id: action for action in REGISTRY}

# What the room API accepts: derived, never hand-listed in portal code (#458).
WEB_ACTIONS = frozenset(i for a in REGISTRY for i in a.web)
ENVELOPE_ACTIONS = frozenset(i for a in REGISTRY if a.envelope for i in a.web)


def gaps() -> list[tuple[str, str]]:
    """(action id, surface) pairs where a surface offers no identifier."""
    return [(a.id, s) for a in REGISTRY for s in SURFACES if not a.on(s)]
