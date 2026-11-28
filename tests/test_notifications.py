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
    assert "self.toast(body, error=event != notifications.FINISHED)" in ui
    assert "self.app.send_notification(" not in ui
    assert "Gio.Notification.new(" not in ui
    assert 'self._switch(alerts, "notifications"' in prefs
    assert '"notifications": True' in widgets
    assert '"notifications"' in package


def test_in_app_alerts_do_not_create_shell_notifications_or_reveal_directories():
    Methods, _namespace = extracted_ui_method("_notify")
    app = SimpleNamespace(send_notification=mock.Mock())
    console = mock.Mock()
    toast = mock.Mock()
    method = Methods()
    method.cfg = {"notifications": True}
    method.app = app
    method._console = console
    method.toast = toast
    method.is_active = lambda: False

    method._notify(notifications.FINISHED, "/private/movies/Film.mkv")
    toast.assert_called_once_with("Film.mkv finished playing.", error=False)
    console.assert_called_once_with("Playback finished: Film.mkv finished playing.")
    assert "/private/" not in str(console.call_args)
    assert "/private/" not in str(toast.call_args)
    app.send_notification.assert_not_called()

    for event, detail, expected in (
        (notifications.ERROR, "Receiver rejected the cast", "Receiver rejected the cast"),
        (notifications.DEVICE_LOST, "Lounge TV", "Lounge TV stopped responding."),
    ):
        toast.reset_mock()
        method._notify(event, detail)
        toast.assert_called_once_with(expected, error=True)
        app.send_notification.assert_not_called()

    toast.reset_mock()
    method.cfg["notifications"] = False
    method._notify(notifications.ERROR, "disabled")
    toast.assert_not_called()
    method.cfg["notifications"] = True
    method.is_active = lambda: True
    method._notify(notifications.ERROR, "focused")
    toast.assert_not_called()

    method.is_active = lambda: False
    toast.side_effect = RuntimeError("toast overlay closed")
    method._notify(notifications.ERROR, "boom")
    assert "In-app playback alert unavailable:" in console.call_args.args[0]
    app.send_notification.assert_not_called()


def test_prefs_explicitly_explain_no_dock_badges():
    ui = source("cast_ui.py")
    prefs = source("preferences_ui.py")
    assert "Ubuntu Dock counted them" in ui
    import settings_catalog
    assert any("never add a counter to the OS dock" in summary
               for _page, groups in settings_catalog.PREFERENCES for _group, summary in groups)
    assert "Show in-app playback alerts" in prefs
