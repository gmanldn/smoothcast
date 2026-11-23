"""Issue #40: sparse hover caches must not affect exact frame-step or casting."""
from __future__ import annotations

import pathlib
import textwrap
from types import SimpleNamespace
from unittest import mock
import screenshot
from gui_source import main_window_methods


def test_sparse_cache_reuses_bins_and_bounds_memory_and_generation():
    cache = screenshot.SparseFrameCache(interval=10, max_entries=2)
    k = cache.key("film.mkv", 1, 0, 12.1)
    assert k == cache.key("film.mkv", 1, 0, 19.9)
    assert cache.sample(19.9) == 10.0
    cache.put(k, b"\xff\xd8frame")
    assert cache.get(k) == b"\xff\xd8frame"
    assert cache.get(cache.key("film.mkv", 2, 0, 12.1)) is None
    assert cache.get(cache.key("film.mkv", 1, 1, 12.1)) is None
    cache.put(cache.key("film.mkv", 1, 0, 20), b"\xff\xd8second")
    cache.get(k)
    cache.put(cache.key("film.mkv", 1, 0, 30), b"\xff\xd8third")
    assert cache.get(cache.key("film.mkv", 1, 0, 20)) is None
    assert len(cache._images) == 2
    cache.put(cache.key("film.mkv", 1, 0, 40), b"not jpeg")
    assert len(cache._images) == 2


def test_cache_rejects_invalid_limits_and_handles_unknown_positions():
    for interval, size in ((0, 10), (float("nan"), 10), (10, 0)):
        try:
            screenshot.SparseFrameCache(interval, size)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid cache accepted")
    cache = screenshot.SparseFrameCache()
    for position in (float("nan"), float("inf"), -5, "bad"):
        assert cache.sample(position) == 0


def test_cached_hover_avoids_another_ffmpeg_but_exact_seek_still_decodes():
    decode = mock.Mock(return_value=b"\xff\xd8JPEG")
    show = mock.Mock()
    def run(work, done=None, failed=None, **_kwargs):
        try:
            value = work()
        except Exception as exc:
            if failed:
                failed(str(exc))
        else:
            if done:
                done(value)
    ns = {
        "pathlib": pathlib,
        "screenshot": SimpleNamespace(SparseFrameCache=screenshot.SparseFrameCache,
                                      preview_frame=decode),
        "Async": SimpleNamespace(run=run),
        "GLib": SimpleNamespace(Bytes=SimpleNamespace(new=lambda data: data),
                                 Error=ValueError, timeout_add=lambda *_: 1),
        "Gdk": SimpleNamespace(Texture=SimpleNamespace(new_from_bytes=lambda data: data)),
    }
    source = main_window_methods()["_start_preview"]
    exec(compile("class Window:\n" + textwrap.indent(textwrap.dedent(source), "    "),
                 "<preview-cache>", "exec"), ns)
    window = ns["Window"]()
    window._preview_timer_id, window._preview_busy = 0, False
    window._preview_pending = ("film.mkv", 12, 1)
    window._preview_path, window._preview_generation = "film.mkv", 1
    window._preview_sparse, window.session, window.external = True, None, False
    window.media = SimpleNamespace(path="film.mkv", is_audio_only=False, video_stream_index=0)
    window.cfg = {}
    window.preview_picture = SimpleNamespace(set_paintable=show, set_visible=mock.Mock())
    window._start_preview()
    decode.assert_called_once_with(pathlib.Path("film.mkv"), 10, video_stream_index=0)
    window._preview_pending, window._preview_sparse = ("film.mkv", 19, 1), True
    window._start_preview()
    assert decode.call_count == 1
    window._preview_pending, window._preview_sparse = ("film.mkv", 19, 1), False
    window._start_preview()
    assert decode.call_count == 2
    assert decode.call_args.args[1] == 19


def test_hover_is_approximate_only_while_exact_frame_step_remains_precise():
    methods = main_window_methods()
    assert "self._queue_preview(value, sparse=True)" in methods["_on_hover"]
    assert "self._preview_sparse = sparse" in methods["_queue_preview"]
    assert "GLib.timeout_add(180, self._start_preview)" in methods["_queue_preview"]
    assert "if self._preview_busy" in methods["_start_preview"]
    assert "cached = cache.get(key)" in methods["_start_preview"]
    assert "pathlib.Path(path), position, video_stream_index=video_index" in methods["_start_preview"]
