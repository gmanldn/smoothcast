"""Headless regression tests for desktop notification policy and wiring (#267)."""
from __future__ import annotations

import ast
from pathlib import Path
import textwrap
from types import SimpleNamespace
from unittest import mock

import notifications

ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / "src" / name).read_text(encoding="utf-8")


class _Notification:
    def __init__(self, title):
        self.title = title
        self.body = ""

    def set_body(self, body):
        self.body = body


def extracted_ui_method(name: str):
    text = source("cast_ui.py")
    tree = ast.parse(text)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "UiMixin")
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    segment = "".join(text.splitlines(keepends=True)[method.lineno - 1:method.end_lineno])
    namespace = {
        "notifications": notifications,
        "pathlib": SimpleNamespace(Path=Path),
        "Gio": SimpleNamespace(Notification=SimpleNamespace(new=_Notification)),
    }
    exec(compile("class Methods:\n" + textwrap.indent(textwrap.dedent(segment), "    "),
                 "<notify-method>", "exec"), namespace)
    return namespace["Methods"], namespace


def test_policy_defaults_on_and_allow_lists_events():
    assert notifications.enabled({})
    assert notifications.enabled({"notifications": True})
    assert not notifications.enabled({"notifications": False})
    for event in notifications.EVENTS:
        assert notifications.should_notify({}, event, window_active=False)
        assert not notifications.should_notify({}, event, window_active=True)
    assert not notifications.should_notify({}, "unknown", window_active=False)
    assert not notifications.should_notify(
        {"notifications": False}, notifications.FINISHED, window_active=False)


def test_finished_error_and_device_lost_are_wired():
    ui = source("cast_ui.py")
    session = source("cast_session.py")
    prefs = source("preferences_ui.py")
    widgets = source("cast_widgets.py")
    package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "import notifications" in ui
    assert 'self._notify("finished", item or "")' in session
    assert 'self._notify("error", message)' in session
    assert "self._notify(notifications.DEVICE_LOST, self._device())" in ui
    assert "notifications.should_notify(self.cfg, event, window_active=active)" in ui
    assert "self.app.send_notification(None, notification)" in ui
    assert 'self._switch(alerts, "notifications"' in prefs
    assert '"notifications": True' in widgets
    assert '"notifications"' in package


def test_notify_respects_disabled_focus_and_event_payloads():
    Methods, namespace = extracted_ui_method("_notify")
    app = SimpleNamespace(send_notification=mock.Mock())
    console = mock.Mock()
    method = Methods()
    method.cfg = {"notifications": True}
    method.app = app
    method._console = console
    method.is_active = lambda: False

    method._notify(notifications.FINISHED, "/media/Film.mkv")
    app.send_notification.assert_called_once()
    sent = app.send_notification.call_args.args[1]
    assert sent.title == "Playback finished"
    assert sent.body == "Film.mkv finished playing."

    app.send_notification.reset_mock()
    method._notify(notifications.ERROR, "Receiver rejected the cast")
    assert app.send_notification.call_count == 1
    assert app.send_notification.call_args.args[1].title == "Playback error"

    app.send_notification.reset_mock()
    method.cfg["notifications"] = False
    method._notify(notifications.ERROR, "disabled")
    app.send_notification.assert_not_called()

    method.cfg["notifications"] = True
    method.is_active = lambda: True
    method._notify(notifications.ERROR, "focused")
    app.send_notification.assert_not_called()

    method.is_active = lambda: False
    app.send_notification.side_effect = RuntimeError("no daemon")
    method._notify(notifications.ERROR, "boom")
    console.assert_called_once()
