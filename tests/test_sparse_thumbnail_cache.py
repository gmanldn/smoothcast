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


def test_nearby_returns_only_same_source_generation_and_stream_in_time_order():
    cache = screenshot.SparseFrameCache(interval=10, max_entries=8)
    for position in (0, 10, 20, 30):
        cache.put(cache.key("film.mkv", 4, 2, position),
                  b"\xff\xd8" + str(position).encode())
    cache.put(cache.key("other.mkv", 4, 2, 20), b"\xff\xd8other")
    cache.put(cache.key("film.mkv", 3, 2, 20), b"\xff\xd8old")
    cache.put(cache.key("film.mkv", 4, 1, 20), b"\xff\xd8stream")

    frames = cache.nearby("film.mkv", 4, 2, 19, radius=2)
    assert frames == [(0, b"\xff\xd80"), (10, b"\xff\xd810"),
                      (20, b"\xff\xd820"), (30, b"\xff\xd830")]
    assert len(cache.nearby("film.mkv", 4, 2, 19, limit=2)) == 2
    assert cache.nearby("film.mkv", 4, 2, 19, limit=0) == []


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
    methods = main_window_methods()
    source = "\n\n".join(methods[name] for name in
                           ("_start_preview", "_refresh_thumbnail_strip"))
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
    assert "self._refresh_thumbnail_strip(position, visible=True)" in methods["_start_preview"]
    assert "self.seek_to(positions[index])" in methods["_on_thumbnail_clicked"]


def test_thumbnail_strip_uses_nearby_cached_frames_and_exact_click_positions():
    methods = main_window_methods()
    names = ("_thumbnail_identity", "_refresh_thumbnail_strip", "_on_thumbnail_clicked")
    source = "\n\n".join(methods[name] for name in names)
    corrupt = b"\xff\xd8corrupt"

    def texture(data):
        if data == corrupt:
            raise ValueError("Invalid JPEG")
        return data

    decode = mock.Mock(side_effect=texture)
    ns = {
        "Gdk": SimpleNamespace(Texture=SimpleNamespace(new_from_bytes=decode)),
        "GLib": SimpleNamespace(Bytes=SimpleNamespace(new=lambda data: data), Error=ValueError),
        "Gtk": SimpleNamespace(AccessibleProperty=SimpleNamespace(LABEL="label")),
        "fmt_time": lambda value: f"{value:g}",
    }
    exec(compile("class Window:\n" + textwrap.indent(textwrap.dedent(source), "    "),
                 "<thumbnail-strip>", "exec"), ns)
    window = ns["Window"]()
    window._preview_path, window._preview_generation = "film.mkv", 1
    window.media = SimpleNamespace(path="film.mkv", is_audio_only=False, video_stream_index=0)
    window.session, window.external = None, False
    window._sparse_frame_cache = screenshot.SparseFrameCache(interval=10)
    for moment in (0, 10, 20):
        window._sparse_frame_cache.put(
            window._sparse_frame_cache.key("film.mkv", 1, 0, moment),
            b"\xff\xd8" + str(moment).encode(),
        )
    window._sparse_frame_cache.put(window._sparse_frame_cache.key("film.mkv", 1, 0, 30), corrupt)
    window.thumbnail_strip = SimpleNamespace(set_visible=mock.Mock())
    window.thumbnail_buttons = [mock.Mock() for _ in range(5)]
    window.thumbnail_pictures = [SimpleNamespace(set_paintable=mock.Mock()) for _ in range(5)]
    window.thumbnail_times = [SimpleNamespace(set_text=mock.Mock()) for _ in range(5)]
    window._refresh_thumbnail_strip(11, visible=True)
    assert window._thumbnail_positions == [0, 10, 20]
    assert [button.set_visible.call_args.args[0] for button in window.thumbnail_buttons] == [
        True, True, True, False, False,
    ]
    window._refresh_thumbnail_strip(12, visible=True)
    assert decode.call_count == 4  # Unchanged cached images keep their existing textures.
    window.seek_to = mock.Mock()
    window._on_thumbnail_clicked(None, 1)
    window.seek_to.assert_called_once_with(10)
    window._preview_generation += 1
    window._on_thumbnail_clicked(None, 1)
    window.seek_to.assert_called_once_with(10)  # No seek after the source generation changed.
    assert window._thumbnail_positions == []
    assert all(picture.set_paintable.call_args.args == (None,) for picture in window.thumbnail_pictures)
    window.thumbnail_strip.set_visible.assert_called_with(False)
