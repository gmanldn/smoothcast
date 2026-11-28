"""Cancellable, receiver-independent preparation of the next queue item."""
from __future__ import annotations

import pathlib
import threading

import playback_state
import queue_metadata
import streamer
from cast_widgets import Async


class QueuePrewarmController:
    """Composition replacement for QueuePrewarmMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _queue_duration_paths(self, paths: list[str]) -> tuple[str, ...]:
        w = self.w
        w._cancel_queue_prewarm()
        target = w._next_queue_item()
        missing = tuple(dict.fromkeys(p for p in paths if p not in w.queue_durations))
        cached = queue_metadata.cached_media(w._media_cache, target) if target else None
        if target in missing and cached is not None:
            w.queue_durations.setdefault(target, cached.duration)
        if target and cached is None:
            w._prewarm_queue_media()
        return tuple(path for path in missing if path != target or cached is not None)

    def _next_queue_item(self) -> str | None:
        w = self.w
        current = w.now_playing or getattr(w, "_local_video_path", None)
        following = playback_state.next_media(
            current, w.queue,
            repeat_current=bool(w.cfg.get("loop")),
            auto_next=bool(w.cfg.get("autonext")),
            repeat_all=bool(w.cfg.get("loop_all")),
        )
        return following if following and following != current else None

    def _cancel_queue_prewarm(self) -> None:
        w = self.w
        cancel = getattr(w, "_queue_prewarm_cancel", None)
        if cancel is not None:
            cancel.set()
        w._queue_prewarm_cancel = None
        w._queue_prewarm_generation = getattr(w, "_queue_prewarm_generation", 0) + 1

    def _prewarm_queue_media(self) -> None:
        """Read the next file's metadata only; do not prepare or command a receiver."""
        w = self.w
        w._cancel_queue_prewarm()
        target = w._next_queue_item()
        if target is None or queue_metadata.cached_media(
                getattr(w, "_media_cache", {}), target) is not None:
            return
        cancel = threading.Event()
        w._queue_prewarm_cancel = cancel
        generation = w._queue_prewarm_generation

        def work():
            return queue_metadata.inspect_media(
                (target,),
                lambda path: streamer.ffprobe(pathlib.Path(path), cancel=cancel),
                cancelled=cancel,
            )

        def done(results):
            w._queue_prewarm_cancel = None
            if w._closing or w._next_queue_item() != target:
                return
            queue_metadata.publish_media(
                w._media_cache, w.queue, results,
            )
            entry = w._media_cache.get(target)
            if entry is not None:
                w.queue_durations.setdefault(target, entry[1].duration)
                w._rebuild_queue()

        def failed(message):
            w._queue_prewarm_cancel = None
            if not w._closing and "prewarm cancelled" not in str(message).lower():
                w._console(f"Next-item prewarm unavailable: {message}")

        Async.run(
            work, done=done, failed=failed, domain="media",
            valid=lambda: (not w._closing
                           and generation == w._queue_prewarm_generation),
        )

    @classmethod
    def install(cls, window) -> "QueuePrewarmController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in QUEUE_PREWARM_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


QUEUE_PREWARM_CONTROLLER_METHODS = ('_queue_duration_paths', '_next_queue_item', '_cancel_queue_prewarm', '_prewarm_queue_media')
