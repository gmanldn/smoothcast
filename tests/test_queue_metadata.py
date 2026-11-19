"""Queue duration work remains GTK-thread owned while FFprobe runs in workers.

Executes the actual QueueMixin handler via its source AST. No Gtk imports,
desktop windows, real media decoders or network receiver commands.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import pathlib
import threading
import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
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
    exec(compile(code, "<queue-metadata-handler>", "exec"), namespace)

    class Window(namespace["Extracted"]):
        def __init__(self):
            self.queue = []
            self.queue_durations = MainThreadDict(durations or {})
            self.queue_durations.owner_thread = threading.get_ident()
            self.now_playing = "current-film"
            self.selected_index = 0
            self._closing = False
            self._rebuild_queue = mock.Mock()
            self.toast = mock.Mock()
            self.set_selection = mock.Mock()

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
