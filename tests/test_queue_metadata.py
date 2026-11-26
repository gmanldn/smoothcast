"""Queue duration work remains GTK-thread owned while FFprobe runs in workers.

Executes the actual QueueMixin handler via its source AST. No Gtk imports,
desktop windows, real media decoders or network receiver commands.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import pathlib
import tempfile
import threading
import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import handler_globals, main_window_methods
import queue_metadata


class MainThreadDict(dict):
    """Fail deterministically if a worker reads or writes GUI-owned state."""

    def _guard(self):
        assert threading.get_ident() == self.owner_thread, "GUI state accessed off-thread"

    def __contains__(self, key):
        self._guard()
        return super().__contains__(key)

    def __setitem__(self, key, value):
        self._guard()
        return super().__setitem__(key, value)

    def setdefault(self, key, default=None):
        self._guard()
        return super().setdefault(key, default)


def window(*, durations=None, probe=None):
    jobs = []
    code = (
        "class Extracted:\n"
        + textwrap.indent(textwrap.dedent(main_window_methods()["_enqueue"]), "    ")
    )
    media_probe = probe or mock.Mock(return_value=SimpleNamespace(duration=101.5))
    namespace = {
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **options:
                jobs.append((work, done, failed, options))
        ),
        "pathlib": pathlib,
        "streamer": SimpleNamespace(ffprobe=media_probe),
        "queue_metadata": queue_metadata,
    }
    namespace.update(handler_globals())
    exec(compile(code, "<queue-metadata-handler>", "exec"), namespace)

    class Window(namespace["Extracted"]):
        def __init__(self):
            self.queue = []
            self.queue_durations = MainThreadDict(durations or {})
            self.queue_durations.owner_thread = threading.get_ident()
            self.now_playing = "current-film"
            self.selected_index = 0
            self.busy = False
            self.session = None
            self.external = False
            self._closing = False
            self._media_cache = {}
            self._rebuild_queue = mock.Mock()
            self.toast = mock.Mock()
            self.set_selection = mock.Mock()
            self._next_queue_item = mock.Mock(return_value=None)
            self._cancel_queue_prewarm = mock.Mock()
            self._prewarm_queue_media = mock.Mock()
            self._queue_duration_paths = mock.Mock(
                side_effect=lambda paths: tuple(dict.fromkeys(
                    path for path in paths if path not in self.queue_durations
                ))
            )

    return Window(), jobs, media_probe


def test_metadata_is_collected_off_thread_but_published_only_on_main_thread():
    w, jobs, ffprobe = window()
    w._enqueue(["a.mkv", "b.mp4"])
    assert w.queue == ["a.mkv", "b.mp4"]
    assert w.queue_durations == {}
    assert w._rebuild_queue.call_count == 1

    work, done, failed, options = jobs.pop()
    assert options["domain"] == "media"
    assert options["valid"]() is True
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(work).result(timeout=3)
    assert result == {"a.mkv": 101.5, "b.mp4": 101.5}
    assert w.queue_durations == {}  # worker never publishes UI state
    done(result)
    assert w.queue_durations == result
    assert w._rebuild_queue.call_count == 2
    assert ffprobe.call_count == 2
    assert failed is None


def test_removed_items_are_not_resurrected_by_slow_probe():
    w, jobs, _ = window()
    w._enqueue(["deleted.mkv", "retained.mkv"])
    work, done, _, _ = jobs.pop()
    measurements = work()
    w.queue.remove("deleted.mkv")
    done(measurements)
    assert w.queue_durations == {"retained.mkv": 101.5}
    assert "deleted.mkv" not in w.queue


def test_newer_duration_wins_over_stale_worker():
    w, jobs, _ = window()
    w._enqueue(["film.mkv"])
    work, done, _, _ = jobs.pop()
    measurements = work()
    w.queue_durations["film.mkv"] = 222.0
    done(measurements)
    assert w.queue_durations["film.mkv"] == 222.0


def test_cached_paths_are_not_reprobed_and_missing_film_is_zero_duration():
    def inspect(path):
        if str(path) == "broken.mkv":
            raise OSError("missing film")
        return SimpleNamespace(duration=87.5)

    w, jobs, _ = window(durations={"cached.mkv": 48.0}, probe=mock.Mock(side_effect=inspect))
    w._enqueue(["cached.mkv", "broken.mkv", "good.mkv"])
    work, done, _, _ = jobs.pop()
    results = work()
    assert results == {"broken.mkv": 0.0, "good.mkv": 87.5}
    done(results)
    assert w.queue_durations == {
        "cached.mkv": 48.0, "broken.mkv": 0.0, "good.mkv": 87.5,
    }


def test_close_invalidates_delayed_metadata_callback():
    w, jobs, _ = window()
    w._enqueue(["film.mkv"])
    _, _, _, opts = jobs.pop()
    assert opts["valid"]() is True
    w._closing = True
    assert opts["valid"]() is False


def test_no_second_probe_for_duplicate_enqueue():
    w, jobs, ffprobe = window()
    w._enqueue(["a.mkv", "a.mkv"])
    assert w.queue == ["a.mkv"]
    assert len(jobs) == 1
    jobs[0][0]()
    assert ffprobe.call_count == 1
    w._enqueue(["a.mkv"])
    assert len(jobs) == 1
    w.toast.assert_called_once()


def test_pure_metadata_publish_ignores_removed_and_preserves_known_values():
    cache = {"newer": 12.0}
    queue_metadata.publish(
        cache, ("newer", "active"), {"newer": 10.0, "active": 2.0, "removed": 9.0}
    )
    assert cache == {"newer": 12.0, "active": 2.0}


def test_queue_title_uses_fresh_embedded_tags_and_falls_back_to_filename():
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "track01.flac"
        path.write_bytes(b"audio")
        media = SimpleNamespace(title="Track title", artist="Artist", album="Album")
        cache = {str(path): (queue_metadata.file_fingerprint(path), media)}

        assert queue_metadata.display_title(path, cache) == "Artist — Track title · Album"
        assert queue_metadata.display_title(path, {}) == "track01.flac"


def test_media_metadata_is_fingerprint_checked_and_bounded():
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "film.mkv"
        path.write_bytes(b"video")
        fingerprint = queue_metadata.file_fingerprint(path)
        media = SimpleNamespace(duration=12.5)
        result = queue_metadata.inspect_media(
            (str(path),), lambda _path: media,
        )
        cache = {}
        queue_metadata.publish_media(cache, (str(path),), result, max_entries=1)
        assert queue_metadata.cached_media(cache, path) is media

        path.write_bytes(b"changed video")
        assert queue_metadata.cached_media(cache, path) is None
        assert result[str(path)].fingerprint == fingerprint
        refreshed = SimpleNamespace(duration=14.0)
        media_used, reused_fingerprint = queue_metadata.media_for_cast(
            cache[str(path)], path, lambda _path: refreshed,
        )
        assert media_used is refreshed and reused_fingerprint is None

        cache[str(path)] = (queue_metadata.file_fingerprint(path), media)
        media_used, reused_fingerprint = queue_metadata.media_for_cast(
            cache[str(path)], path, lambda _path: refreshed,
        )
        assert media_used is media and reused_fingerprint == cache[str(path)][0]


def test_media_probe_discards_results_after_cancellation_or_file_change():
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "film.mkv"
        path.write_bytes(b"video")
        cancel = threading.Event()

        def probe(_path):
            cancel.set()
            return SimpleNamespace(duration=5.0)

        assert queue_metadata.inspect_media(
            (str(path),), probe, cancelled=cancel,
        ) == {}


def test_media_publish_only_keeps_queued_current_files_and_respects_bound():
    with tempfile.TemporaryDirectory() as directory:
        paths = [pathlib.Path(directory) / f"{index}.mkv" for index in range(3)]
        for path in paths:
            path.write_bytes(b"x")
        results = queue_metadata.inspect_media(
            map(str, paths), lambda path: SimpleNamespace(path=path),
        )
        cache = {}
        queue_metadata.publish_media(cache, (str(paths[0]), str(paths[1])), results,
                                     max_entries=1)
        assert len(cache) == 1
        assert str(paths[2]) not in cache


def test_background_enqueue_never_auto_selects_during_receiver_preparation():
    w, jobs, _ = window()
    w.now_playing = None
    w.selected_index = None
    w.busy = True
    w._enqueue(["background.mkv"])
    assert w.queue == ["background.mkv"]
    assert len(jobs) == 1
    w.set_selection.assert_not_called()


def test_idle_empty_queue_still_selects_first_media():
    w, _, _ = window()
    w.now_playing = None
    w.selected_index = None
    w._enqueue(["first.mkv"])
    w.set_selection.assert_called_once_with("first.mkv")
