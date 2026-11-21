"""Queue prewarming reads metadata in workers and never owns a receiver."""
from __future__ import annotations

import ast
import pathlib
import threading
from types import SimpleNamespace
from unittest import mock

import playback_state
import queue_metadata


def load_mixin(async_jobs, ffprobe):
    source = pathlib.Path(__file__).parents[1] / "src" / "queue_prewarm_ui.py"
    tree = ast.parse(source.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = {
        "pathlib": pathlib,
        "threading": threading,
        "playback_state": playback_state,
        "queue_metadata": queue_metadata,
        "streamer": SimpleNamespace(ffprobe=ffprobe),
        "Async": SimpleNamespace(run=async_jobs),
    }
    module = ast.Module(body=[cls], type_ignores=[])
    exec(compile(module, str(source), "exec"), namespace)
    return namespace[cls.name]


class Window:
    def __init__(self):
        self.queue = []
        self.now_playing = None
        self._local_video_path = None
        self.cfg = {"autonext": True, "loop": False, "loop_all": False}
        self._media_cache = {}
        self.queue_durations = {}
        self._closing = False
        self._rebuild_queue = mock.Mock()
        self._console = mock.Mock()


def test_next_item_is_prepared_without_receiver_work_and_published_on_main_thread(tmp_path):
    path = tmp_path / "next.mkv"
    path.write_bytes(b"video")
    jobs = []
    media = SimpleNamespace(duration=93.0)
    ffprobe = mock.Mock(return_value=media)
    mixin = load_mixin(
        lambda work, done=None, failed=None, **options:
            jobs.append((work, done, failed, options)), ffprobe,
    )
    window = Window()
    window.__class__ = type("Window", (mixin, Window), {})
    window.queue = ["current.mkv", str(path)]
    window.now_playing = "current.mkv"

    window._prewarm_queue_media()
    work, done, _, options = jobs.pop()
    assert options["domain"] == "media"
    assert options["valid"]()
    results = work()
    assert ffprobe.call_args.args[0] == path
    assert "cancel" in ffprobe.call_args.kwargs
    assert window._media_cache == {}
    done(results)
    assert window._media_cache[str(path)][1] is media
    assert window.queue_durations[str(path)] == 93.0
    window._rebuild_queue.assert_called_once_with()


def test_cancellation_invalidates_worker_and_cancellable_probe(tmp_path):
    path = tmp_path / "next.mkv"
    path.write_bytes(b"video")
    jobs = []
    ffprobe = mock.Mock(return_value=SimpleNamespace(duration=10.0))
    mixin = load_mixin(
        lambda work, done=None, failed=None, **options:
            jobs.append((work, done, failed, options)), ffprobe,
    )
    window = Window()
    window.__class__ = type("Window", (mixin, Window), {})
    window.queue = ["current.mkv", str(path)]
    window.now_playing = "current.mkv"
    window._prewarm_queue_media()
    _, _, _, options = jobs[0]
    cancel = window._queue_prewarm_cancel
    window._cancel_queue_prewarm()
    assert cancel.is_set()
    assert not options["valid"]()
    assert not ffprobe.called


def test_auto_next_off_and_repeat_current_do_not_prewarm(tmp_path):
    path = tmp_path / "next.mkv"
    path.write_bytes(b"video")
    jobs = []
    mixin = load_mixin(
        lambda work, done=None, failed=None, **options:
            jobs.append((work, done, failed, options)), mock.Mock(),
    )
    window = Window()
    window.__class__ = type("Window", (mixin, Window), {})
    window.queue = ["current.mkv", str(path)]
    window.now_playing = "current.mkv"
    window.cfg["autonext"] = False
    window._prewarm_queue_media()
    assert jobs == []

    window.cfg.update(autonext=True, loop=True)
    window._prewarm_queue_media()
    assert jobs == []
