"""Headless assertions for the real desktop stale-runtime handler (#540).

Compile only its Python AST, never import or launch Gtk, and never touch
network, TV receivers, user config or a real process.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import version


def handler():
    source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "CastControlApp")
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_show_stale_runtime_notice")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[]))
    namespace = {"version": version, "pathlib": __import__("pathlib")}
    exec(compile(module, "<isolated desktop handler>", "exec"), namespace)
    return namespace["_show_stale_runtime_notice"]


def fake_window():
    messages = []
    window = SimpleNamespace(
        _closing=False, _installed_version_stale=False, update_notice=None,
        _update_header_subtitle=lambda: None,
        toast=lambda text, error=False: messages.append((text, error)),
    )
    return window, messages


def test_same_semantic_version_new_revision_is_reported_once_without_git():
    app = SimpleNamespace(_run_revision="a" * 40, _noticed_runtime_key=None)
    window, messages = fake_window()
    with mock.patch.object(version, "read_checkout_version",
                           return_value=version.__version__), \
         mock.patch.object(version, "read_checkout_revision",
                           return_value="b" * 40):
        fn = handler()
        fn(app, window)
        fn(app, window)
    assert len(messages) == 1
    assert messages[0][1] is True
    assert "bbbbbbbb" in messages[0][0] and "aaaaaaaa" in messages[0][0]
    assert window._installed_version_stale is True


def test_new_version_is_distinguished_from_same_version_revision():
    app = SimpleNamespace(_run_revision="a" * 40, _noticed_runtime_key=None)
    window, messages = fake_window()
    with mock.patch.object(version, "read_checkout_version",
                           return_value="9.9.9"), \
         mock.patch.object(version, "read_checkout_revision",
                           return_value="b" * 40):
        handler()(app, window)
    assert len(messages) == 1
    assert "Installed SmoothCast v9.9.9" in messages[0][0]
    assert f"running v{version.__version__}" in messages[0][0]
    assert "installed" in window.update_notice.lower()


def test_no_stale_notice_for_same_release_or_closing_window():
    app = SimpleNamespace(_run_revision="a" * 40, _noticed_runtime_key=None)
    window, messages = fake_window()
    with mock.patch.object(version, "read_checkout_version",
                           return_value=version.__version__), \
         mock.patch.object(version, "read_checkout_revision",
                           return_value="a" * 40):
        handler()(app, window)
    assert messages == []
    window._closing = True
    with mock.patch.object(version, "read_checkout_version",
                           side_effect=AssertionError("closed windows must not query disk")):
        handler()(app, window)
    assert messages == []


def test_missing_git_metadata_does_not_fabricate_new_version():
    app = SimpleNamespace(_run_revision=None, _noticed_runtime_key=None)
    window, messages = fake_window()
    with mock.patch.object(version, "read_checkout_version",
                           return_value=version.__version__), \
         mock.patch.object(version, "read_checkout_revision", return_value=None):
        handler()(app, window)
    assert messages == []
