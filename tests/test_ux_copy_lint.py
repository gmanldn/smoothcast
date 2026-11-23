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
    raise RoomError(403, "x" * 250)
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
