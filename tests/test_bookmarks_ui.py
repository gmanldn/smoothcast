"""GTK-free behavioral checks for bookmark save and verified seek callbacks."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import textwrap
import time
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import bookmarks


class ImmediateAsync:
    @staticmethod
    def run(work, done=None, failed=None, **_kwargs):
        try:
            result = work()
        except Exception as exc:
            if failed:
                failed(str(exc))
        else:
            if done:
                done(result)


class FakeEntry:
    def __init__(self):
        self.value = ""

    def set_text(self, value):
        self.value = value

    def set_max_length(self, _length):
        pass

    def set_activates_default(self, _active):
        pass

    def get_text(self):
        return self.value


class FakeDialog:
    last = None

    def __init__(self):
        type(self).last = self
        self.response = None

    @classmethod
    def new(cls, *_args):
        return cls()

    def set_extra_child(self, entry):
        self.entry = entry

    def add_response(self, *_args):
        pass

    def set_default_response(self, *_args):
        pass

    def set_response_appearance(self, *_args):
        pass

    def connect(self, _signal, callback):
        self.response = callback

    def present(self, _parent):
        pass


def methods(*names):
    source = (ROOT / "src" / "cast_ui.py").read_text("utf-8")
    tree = ast.parse(source)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "UiMixin")
    found = {node.name: ast.get_source_segment(source, node) for node in owner.body
             if isinstance(node, ast.FunctionDef)}
    body = "\n\n".join(textwrap.indent(textwrap.dedent(found[name]), "    ") for name in names)
    namespace = {
        "bookmarks": bookmarks, "Async": ImmediateAsync, "Gtk": SimpleNamespace(Entry=FakeEntry),
        "Adw": SimpleNamespace(AlertDialog=FakeDialog, ResponseAppearance=SimpleNamespace(SUGGESTED=1)),
        "fmt_time": lambda seconds: f"{int(seconds)}s", "save_config": mock.Mock(),
        "time": time, "FakeDialog": FakeDialog,
    }
    exec(compile("class UI:\n" + body, "<bookmark-methods>", "exec"), namespace)
    namespace["UI"].testing_globals = namespace
    return namespace["UI"]


def window(path: Path, digest: str):
    UI = methods("_bookmark_current", "_prompt_bookmark_name", "_open_bookmark")
    ui = UI()
    ui.session = None
    ui._preview_path = str(path)
    ui._preview_position = 24.5
    ui.now_playing = None
    ui.tracker = SimpleNamespace(value=lambda: None)
    ui.cfg = {"bookmarks": [{
        "fingerprint": digest, "name": "Favourite scene", "media": "film.mkv",
        "position": 12.0, "created": 1.0,
    }]}
    ui.seek_to = mock.Mock()
    ui.toast = mock.Mock()
    ui.menu_button = SimpleNamespace(set_menu_model=mock.Mock())
    ui._build_menu = mock.Mock(return_value=object())
    return ui


def test_bookmark_jump_requires_same_content_and_uses_saved_position(tmp_path):
    media = tmp_path / "film.mkv"
    media.write_bytes(b"same content")
    digest = bookmarks.fingerprint(media)
    ui = window(media, digest)
    ui._open_bookmark(0)
    ui.seek_to.assert_called_once_with(12.0)
    ui.toast.assert_called_once_with("Checking bookmark media…")


def test_bookmark_jump_refuses_different_media_without_seeking(tmp_path):
    media = tmp_path / "other.mkv"
    media.write_bytes(b"different content")
    ui = window(media, "a" * 64)
    ui._open_bookmark(0)
    ui.seek_to.assert_not_called()
    assert ui.toast.call_count == 2
    assert "belongs to film.mkv" in ui.toast.call_args.args[0]


def test_named_bookmark_dialog_persists_marker_and_refreshes_menu(tmp_path):
    media = tmp_path / "film.mkv"
    media.write_bytes(b"video")
    digest = bookmarks.fingerprint(media)
    ui = window(media, digest)
    ui._prompt_bookmark_name(str(media), media.name, 24.5, digest)
    instance = ui.testing_globals["FakeDialog"].last
    instance.entry.value = "Key scene"
    instance.response(instance, "save")
    assert ui.cfg["bookmarks"][0]["name"] == "Key scene"
    assert ui.cfg["bookmarks"][0]["position"] == 24.5
    ui.testing_globals["save_config"].assert_called_once_with(ui.cfg)
    ui.menu_button.set_menu_model.assert_called_once()
