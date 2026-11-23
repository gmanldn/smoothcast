"""Cancellable, receiver-independent preparation of the next queue item."""
from __future__ import annotations

import pathlib
import threading

import playback_state
import queue_metadata
import streamer
from cast_widgets import Async


class QueuePrewarmMixin:
    def _queue_duration_paths(self, paths: list[str]) -> tuple[str, ...]:
        self._cancel_queue_prewarm()
        target = self._next_queue_item()
        missing = tuple(dict.fromkeys(p for p in paths if p not in self.queue_durations))
        cached = queue_metadata.cached_media(self._media_cache, target) if target else None
        if target in missing and cached is not None:
            self.queue_durations.setdefault(target, cached.duration)
        if target and cached is None:
            self._prewarm_queue_media()
        return tuple(path for path in missing if path != target or cached is not None)

    def _next_queue_item(self) -> str | None:
        current = self.now_playing or getattr(self, "_local_video_path", None)
        following = playback_state.next_media(
            current, self.queue,
            repeat_current=bool(self.cfg.get("loop")),
            auto_next=bool(self.cfg.get("autonext")),
            repeat_all=bool(self.cfg.get("loop_all")),
        )
        return following if following and following != current else None

    def _cancel_queue_prewarm(self) -> None:
        cancel = getattr(self, "_queue_prewarm_cancel", None)
        if cancel is not None:
            cancel.set()
        self._queue_prewarm_cancel = None
        self._queue_prewarm_generation = getattr(self, "_queue_prewarm_generation", 0) + 1

    def _prewarm_queue_media(self) -> None:
        """Read the next file's metadata only; do not prepare or command a receiver."""
        self._cancel_queue_prewarm()
        target = self._next_queue_item()
        if target is None or queue_metadata.cached_media(
                getattr(self, "_media_cache", {}), target) is not None:
            return
        cancel = threading.Event()
        self._queue_prewarm_cancel = cancel
        generation = self._queue_prewarm_generation

        def work():
            return queue_metadata.inspect_media(
                (target,),
                lambda path: streamer.ffprobe(pathlib.Path(path), cancel=cancel),
                cancelled=cancel,
            )

        def done(results):
            self._queue_prewarm_cancel = None
            if self._closing or self._next_queue_item() != target:
                return
            queue_metadata.publish_media(
                self._media_cache, self.queue, results,
            )
            entry = self._media_cache.get(target)
            if entry is not None:
                self.queue_durations.setdefault(target, entry[1].duration)
                self._rebuild_queue()

        def failed(message):
            self._queue_prewarm_cancel = None
            if not self._closing and "prewarm cancelled" not in str(message).lower():
                self._console(f"Next-item prewarm unavailable: {message}")

        Async.run(
            work, done=done, failed=failed, domain="media",
            valid=lambda: (not self._closing
                           and generation == self._queue_prewarm_generation),
        )
