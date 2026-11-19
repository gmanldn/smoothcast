"""Executable playlist-chooser regressions; no GTK display or user files.

P1 SC-079 #88: loading/saving named playlists must run I/O off the GTK thread,
keep the queue unchanged on cancel/failure, and expose a real chooser.
"""
from __future__ import annotations

import pathlib
import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods
import playlist_control


class FakeGLibError(Exception):
    pass


class FakeGLib:
    Error = FakeGLibError


class FakeGFile:
    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path


class FakeDialog:
    def __init__(self, path=None, cancelled=False):
        self.path = path
        self.cancelled = cancelled

    def open_finish(self, _result):
        if self.cancelled:
            raise FakeGLibError("dismissed")
        return FakeGFile(self.path)

    def save_finish(self, _result):
        if self.cancelled:
            raise FakeGLibError("dismissed")
        return FakeGFile(self.path)


def extracted(*names, jobs):
    code = "class Methods:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(main_window_methods()[name]), "    ")
        for name in names
    )
    namespace = {
        "playlist_control": playlist_control,
        "pathlib": pathlib,
        "GLib": FakeGLib,
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None:
                                 jobs.append((work, done, failed))),
    }
    exec(compile(code, "<playlist-handlers>", "exec"), namespace)
    return namespace["Methods"]


def window(*names):
    jobs = []
    Methods = extracted(*names, jobs=jobs)

    class Window(Methods):
        def __init__(self):
            self.queue = []
            self.toast = mock.Mock()

            def enqueue(paths):
                self.queue.extend(paths)

            self._enqueue = enqueue

    return Window(), jobs


def _media(tmp, name):
    path = tmp / name
    path.write_bytes(b"media")
    return str(path)


def test_open_chooser_loads_two_named_playlists_off_thread(tmp_path):
    first = _media(tmp_path, "one.mp4")
    second = _media(tmp_path, "two.mp4")
    other = _media(tmp_path, "three.mp4")
    list_a = tmp_path / "weekend.m3u"
    list_b = tmp_path / "holiday.m3u"
    playlist_control.save_playlist(list_a, [first, second])
    playlist_control.save_playlist(list_b, [other])

    for chosen, expected in ((list_a, [first, second]), (list_b, [other])):
        w, jobs = window("_playlist_open_chosen")
        w._playlist_open_chosen(FakeDialog(str(chosen)), None)
        assert len(jobs) == 1
        work, done, _ = jobs.pop()
        done(work())  # worker runs the real parser; done applies on the GTK thread
        assert w.queue == expected


def test_cancelled_open_leaves_queue_unchanged():
    w, jobs = window("_playlist_open_chosen")
    w.queue = ["/keep/me.mp4"]
    w._playlist_open_chosen(FakeDialog(cancelled=True), None)
    assert jobs == []
    assert w.queue == ["/keep/me.mp4"]


def test_read_failure_leaves_queue_unchanged():
    w, jobs = window("_playlist_open_chosen")
    w.queue = ["/keep/me.mp4"]
    w._playlist_open_chosen(FakeDialog("/does/not/exist.m3u"), None)
    work, _, failed = jobs.pop()
    try:
        work()
    except Exception as exc:  # PlaylistError from the real parser
        failed(str(exc))
    assert w.queue == ["/keep/me.mp4"]
    assert w.toast.called


def test_save_chooser_writes_the_named_playlist(tmp_path):
    first = _media(tmp_path, "a.mp4")
    second = _media(tmp_path, "b.mp4")
    destination = tmp_path / "my queue.m3u"
    w, jobs = window("_playlist_save_chosen")
    w.queue = [first, second]
    w._playlist_save_chosen(FakeDialog(str(destination)), None)
    work, done, _ = jobs.pop()
    done(work())
    assert destination.exists()
    loaded, skipped = playlist_control.load_playlist(destination)
    assert loaded == [first, second]
    assert skipped == 0


def test_save_cancelled_writes_nothing(tmp_path):
    destination = tmp_path / "never.m3u"
    w, jobs = window("_playlist_save_chosen")
    w.queue = [_media(tmp_path, "a.mp4")]
    w._playlist_save_chosen(FakeDialog(cancelled=True), None)
    assert jobs == []
    assert not destination.exists()


def test_handlers_use_a_chooser_and_async_io():
    methods = main_window_methods()
    load = methods["_load_playlist"]
    save = methods["_save_playlist"]
    assert "Gtk.FileDialog" in load and "dialog.open(" in load
    assert "Gtk.FileDialog" in save and "dialog.save(" in save
    assert "set_initial_name" in save
    assert "Path.home()" not in load and "Path.home()" not in save
    open_chosen = methods["_playlist_open_chosen"]
    assert "Async.run(" in open_chosen
    assert "playlist_control.load_playlist" in open_chosen
    assert "except GLib.Error:" in open_chosen
    save_chosen = methods["_playlist_save_chosen"]
    assert "Async.run(" in save_chosen
    assert "playlist_control.save_playlist" in save_chosen