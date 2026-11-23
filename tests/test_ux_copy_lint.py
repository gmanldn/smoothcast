"""Source copy style is mechanically linted without creating a GTK window."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ux_copy_lint", ROOT / "scripts" / "ci" / "ux_copy_lint.py",
)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


def test_all_current_error_and_toast_literals_pass_copy_gate():
    assert lint.validate(ROOT) == []


def test_copy_gate_flags_old_phrasing_and_raw_exceptions():
    sample = """
def show(self, exc):
    self.toast(str(exc))
    self.toast("Device is offline")
    self.set_title("This title.")
    raise CommandError(409, "Command accepted")
"""
    issues = lint.scan_source(sample)
    assert any("raw exception" in item for item in issues)
    assert any("banned UX phrase 'device is offline'" in item for item in issues)
    assert any("title ends" in item for item in issues)
    assert any("command accepted" in item for item in issues)


def test_copy_gate_enforces_length_bounds_and_allows_gettext_ready_fstrings():
    bad = 'self.toast("' + ("A" * 181) + '")'
    assert any("exceeds 180" in item for item in lint.scan_source(bad))
    good = '''
def success(self, name):
    self.toast(f"Playing {name}")
    self.set_title("Playback")
    raise RoomError(401, "Rejoin the room to continue.")
'''
    assert lint.scan_source(good) == []



def test_copy_gate_checks_every_alternative_and_callable_message_surface():
    overlong_label = "x" * 241
    sample = f"""
def show(self, connected, message):
    self.toast("Receiver connected and ready for playback" if connected else "Oops")
    self.set_text(message or "Invalid request body")
    Gtk.Label(label={overlong_label!r})
    Gtk.Button.new_with_label("Playback.")
    Adw.AlertDialog.new("Choose a receiver.", "Device is offline")
    raise ScreenError(status=409, message="Command accepted")
"""
    assert sorted(lint.scan_source(sample)) == sorted([
        "<source>:8: banned UX phrase 'command accepted'",
        "<source>:3: banned UX phrase 'oops'",
        "<source>:4: banned UX phrase 'invalid request body'",
        "<source>:5: description exceeds 240 characters",
        "<source>:6: title ends with a full stop",
        "<source>:7: title ends with a full stop",
        "<source>:7: banned UX phrase 'device is offline'",
    ])


def test_copy_gate_checks_gettext_templates_and_contained_exception_text():
    sample = """
def show(self, title):
    self.toast(_("Playing {title}").format(title=title))
    self.set_title(f"Receiver. {title}")
    self.toast(gettext("Device is offline"))
    self.toast(_("Command accepted: {title}").format(title=title))
    try:
        start()
    except OSError as cause:
        Adw.Toast.new(f"Could not start: {cause}")
        self.set_text(str(cause) or "Could not start the room.")
"""
    assert sorted(lint.scan_source(sample)) == sorted([
        "<source>:5: banned UX phrase 'device is offline'",
        "<source>:6: banned UX phrase 'command accepted'",
        "<source>:10: raw exception shown to user",
        "<source>:11: raw exception shown to user",
    ])
