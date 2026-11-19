"""Fail-closed subtitle selection for a receiver HLS restart.

The old stream must remain owned and intact until the selected external or
embedded subtitle source is confirmed usable. This module never touches GTK
or the receiver and should be called from the existing background worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamer


@dataclass(frozen=True)
class RestartSubtitles:
    external: Path | None
    burn: bool
    embedded_index: int | None


def validate_restart(state: Any, media: streamer.MediaInfo) -> RestartSubtitles:
    """Resolve exactly the previous caption choice without choosing another.

    Missing/invalid explicit tracks are errors *before* the active session is
    torn down. The source's currently-preferred or forced track is not
    substituted for a saved selection because doing so alters the film.
    """
    if state is None:
        return RestartSubtitles(None, False, None)
    saved = str(getattr(state, "subs", "") or "").strip()
    selected = getattr(state, "embedded_subtitle_index", -1)
    if type(selected) is not int or selected < -1:
        raise streamer.StreamError("Saved embedded subtitle index is invalid; select a track again")
    if saved and selected >= 0:
        raise streamer.StreamError("Conflicting subtitle selections; choose one track before restarting")

    path: Path | None = None
    burn = bool(getattr(state, "burn_subs", False))
    if saved:
        path = Path(saved).expanduser()
        if (path.suffix.lower() not in streamer.SUBTITLE_EXTS
                or not path.is_file()):
            raise streamer.StreamError(
                f"Selected subtitle file is missing or unsupported: {path.name}; "
                "original playback was preserved"
            )
        # A saved non-receiver subtitle format must never silently disappear
        # if an old state record accidentally carries burn_subs=False.
        burn = burn or path.suffix.lower() not in streamer.CAST_SUBTITLE_EXTS

    embedded: int | None = None
    if selected >= 0:
        tracks = getattr(media, "subtitle_tracks", []) or []
        matches = [track for track in tracks
                   if track.index == selected and track.is_text]
        if len(matches) != 1:
            raise streamer.StreamError(
                "Previously selected embedded subtitle track is no longer "
                "available; original playback was preserved"
            )
        embedded = selected
        burn = True

    return RestartSubtitles(path, burn, embedded)
