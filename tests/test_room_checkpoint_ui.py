"""GTK-free recovery prompt and queue checkpoint wiring tests."""
from __future__ import annotations

import textwrap
import json
from types import SimpleNamespace

from gui_source import main_window_methods
import room_checkpoint


class FakeDialog:
    instances = []

    def __init__(self, title, detail):
        self.title = title
        self.detail = detail
        self.responses = []
        self.callback = None
        type(self).instances.append(self)

    @classmethod
    def new(cls, title, detail):
        return cls(title, detail)

    def add_response(self, key, label):
        self.responses.append((key, label))

    def set_default_response(self, _key):
        pass

    def set_close_response(self, _key):
        pass

    def set_response_appearance(self, *_args):
        pass

    def connect(self, _signal, callback):
        self.callback = callback

    def present(self, _parent):
        pass


def recovery_type():
    methods = main_window_methods()
    names = ("_offer_room_recovery", "_recover_room_checkpoint",
             "_discard_room_checkpoint", "_save_room_checkpoint")
    source = "class Recovery:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[name]), "    ") for name in names
    )
    namespace = {
        "room_checkpoint": room_checkpoint,
        "Adw": SimpleNamespace(
            AlertDialog=FakeDialog,
            ResponseAppearance=SimpleNamespace(SUGGESTED=1),
        ),
    }
    exec(compile(source, "<room-recovery-test>", "exec"), namespace)
    return namespace["Recovery"]


def window(checkpoint, *, selftest=False):
    class TestWindow(recovery_type()):
        def __init__(self):
            self.app = SimpleNamespace(selftest=selftest)
            self._room_checkpoint_file = checkpoint
            self._room_checkpoint_last = None
            self._room_checkpoint_error_shown = False
            self.queue = []
            self.queue_durations = {}
            self.selected_index = None
            self.rebuilds = 0
            self.toasts = []
            self.logs = []

        def _rebuild_queue(self):
            self.rebuilds += 1

        def toast(self, message, error=False):
            self.toasts.append((message, error))

        def _console(self, message):
            self.logs.append(message)

    return TestWindow()


def test_startup_prompt_restores_paths_without_restoring_playback(tmp_path):
    FakeDialog.instances.clear()
    files = []
    for index in range(10):
        media = tmp_path / f"{index}.mkv"
        media.write_bytes(b"film")
        files.append(str(media))
    checkpoint = tmp_path / "room.json"
    room_checkpoint.write_checkpoint(checkpoint, files)
    host = window(checkpoint)

    host._offer_room_recovery()
    dialog = FakeDialog.instances[-1]
    assert dialog.title == "Recover previous room?"
    assert "Playback and old guest sessions will not resume" in dialog.detail
    assert {response for response, _label in dialog.responses} == {"keep", "discard", "recover"}
    dialog.callback(dialog, "recover")

    assert host.queue == files
    assert host.selected_index is None
    assert host.queue_durations == {}
    assert host.rebuilds == 1
    assert host.toasts == [("Recovered 10 queued item(s)", False)]
    dialog.callback(dialog, "recover")
    assert host.queue == files, "a repeated recovery response must replace, not duplicate, queue rows"


def test_discard_clears_saved_room_and_damaged_file_is_not_silently_removed(tmp_path):
    FakeDialog.instances.clear()
    checkpoint = tmp_path / "room.json"
    checkpoint.write_text("{bad json", encoding="utf-8")
    host = window(checkpoint)

    host._offer_room_recovery()
    dialog = FakeDialog.instances[-1]
    assert dialog.title == "Previous room could not be read"
    assert checkpoint.exists()
    dialog.callback(dialog, "keep")
    assert checkpoint.exists()
    dialog.callback(dialog, "discard")
    assert room_checkpoint.load_checkpoint(checkpoint).items == ()


def test_guest_and_queue_auth_state_are_not_checkpointed(tmp_path):
    checkpoint = tmp_path / "room.json"
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"film")
    host = window(checkpoint)
    host.queue = [str(media)]

    host._save_room_checkpoint()
    host._save_room_checkpoint()

    assert host._room_checkpoint_last == (str(media),)
    assert host.logs == []
    assert host.toasts == []
    assert host.rebuilds == 0
    stored = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert set(stored) == {"schema_version", "items"}


def test_selftest_mode_never_reads_or_writes_room_state(tmp_path):
    FakeDialog.instances.clear()
    checkpoint = tmp_path / "room.json"
    host = window(checkpoint, selftest=True)
    host._offer_room_recovery()
    host.queue = [str(tmp_path / "film.mkv")]
    host._save_room_checkpoint()
    assert FakeDialog.instances == []
    assert not checkpoint.exists()
