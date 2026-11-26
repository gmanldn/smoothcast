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
        "ROOM_CHECKPOINT_FILE": None,
        "Adw": SimpleNamespace(
            AlertDialog=FakeDialog,
            ResponseAppearance=SimpleNamespace(SUGGESTED=1),
        ),
    }
    exec(compile(source, "<room-recovery-test>", "exec"), namespace)
    return namespace["Recovery"]


def window(checkpoint, *, selftest=False, live_room=True):
    class TestWindow(recovery_type()):
        def __init__(self):
            self.app = SimpleNamespace(selftest=selftest)
            self._room_checkpoint_file = checkpoint
            self._portal = object() if live_room else None
            self._queue_revision = 0
            self._observed_queue = ()
            self.session = object()
            self.tracker = object()
            self._room_checkpoint_last = None
            self._room_checkpoint_error_shown = False
            self.queue = []
            self.queue_durations = {}
            self.selected_index = None
            self.rebuilds = 0
            self.toasts = []
            self.logs = []

        def _portal_observe_queue(self):
            items = tuple(self.queue)
            if items != self._observed_queue:
                self._observed_queue = items
                self._queue_revision += 1
            return self._queue_revision

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

    owned_session, tracker = host.session, host.tracker
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
    assert host.queue == files
    assert host.rebuilds == 1  # Replayed responses cannot restore the same checkpoint twice.
    assert host.session is owned_session and host.tracker is tracker


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
    host._offer_room_recovery()
    discard_dialog = FakeDialog.instances[-1]
    discard_dialog.callback(discard_dialog, "discard")
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



def test_late_prompt_responses_do_not_replace_or_clear_a_new_room_queue(tmp_path):
    old_file = tmp_path / "old.mkv"
    new_file = tmp_path / "new.mkv"
    for media in (old_file, new_file):
        media.write_bytes(b"movie")
    for action in ("recover", "discard"):
        checkpoint = tmp_path / f"{action}.json"
        room_checkpoint.write_checkpoint(checkpoint, [str(old_file)])
        host = window(checkpoint)
        owned_session, tracker = host.session, host.tracker
        host._offer_room_recovery()
        dialog = FakeDialog.instances[-1]
        host.queue = [str(new_file)]
        host._save_room_checkpoint()
        dialog.callback(dialog, action)
        assert host.queue == [str(new_file)]
        assert room_checkpoint.load_checkpoint(checkpoint).items == (str(new_file),)
        assert host.rebuilds == 0
        assert host.session is owned_session and host.tracker is tracker
        assert host.toasts == [("The room queue has changed. The current queue was kept.", True)]


def test_empty_or_local_only_queue_does_not_create_a_room_checkpoint(tmp_path):
    checkpoint = tmp_path / "room.json"
    host = window(checkpoint, live_room=False)
    host.queue = [str(tmp_path / "film.mkv")]
    host._save_room_checkpoint()
    assert not checkpoint.exists()

    host.queue.clear()
    host._portal = object()
    host._save_room_checkpoint()
    assert not checkpoint.exists()


def test_name_only_change_is_saved_and_restored_before_queue_rebuild(tmp_path):
    checkpoint = tmp_path / "room.json"
    media = tmp_path / "opaque.mp4"
    media.write_bytes(b"film")
    host = window(checkpoint)
    host.queue = [str(media)]
    host._save_room_checkpoint()
    host._portal_queue_display_names = {str(media): "Original movie.mp4"}
    host._save_room_checkpoint()
    assert room_checkpoint.load_checkpoint(checkpoint).display_names == (
        (str(media), "Original movie.mp4"),
    )
    restored = window(checkpoint)
    def rebuild():
        assert restored._portal_queue_display_names == {str(media): "Original movie.mp4"}
        restored.rebuilds += 1
    restored._rebuild_queue = rebuild
    restored._recover_room_checkpoint()
    assert restored.rebuilds == 1
