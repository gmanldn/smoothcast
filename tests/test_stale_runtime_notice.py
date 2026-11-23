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
    namespace = {
        "version": version,
        "pathlib": __import__("pathlib"),
        "__file__": str(ROOT / "src" / "cast_control.py"),
    }
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


def test_update_candidate_does_not_hide_stale_installed_generation():
    """An available remote release must not mask a mandatory restart."""
    source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "CastControlApp")
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_present_update_notice")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[]))
    namespace = {}
    exec(compile(module, "<isolated notice presenter>", "exec"), namespace)
    presenter = namespace["_present_update_notice"]
    calls = []
    window = SimpleNamespace(
        _closing=False, _installed_version_stale=True,
        update_notice="Installed v2; running v1; restart",
        _update_header_subtitle=lambda: calls.append("header"),
        _console=lambda msg: calls.append(("console", msg)),
        toast=lambda msg: calls.append(("toast", msg)),
    )
    assert presenter(SimpleNamespace(window=window), "v3 is available") is False
    assert window.update_notice == "Installed v2; running v1; restart"
    assert "header" not in calls
    assert ("console", "v3 is available") in calls

    window._installed_version_stale = False
    assert presenter(SimpleNamespace(window=window), "v3 is available") is False
    assert window.update_notice == "v3 is available"
    assert "header" in calls

    window._closing = True
    calls.clear()
    assert presenter(SimpleNamespace(window=window), "later") is False
    assert not calls



def test_rollback_to_running_generation_clears_stale_header_and_allows_rewarning():
    """A safe rollback must not leave a false restart-required notice."""
    app = SimpleNamespace(_run_revision="a" * 40, _noticed_runtime_key=None)
    headers = []
    window, messages = fake_window()
    window._update_header_subtitle = lambda: headers.append(window.update_notice)
    revisions = iter(["b" * 40, "a" * 40, "b" * 40])
    with mock.patch.object(version, "read_checkout_version",
                           return_value=version.__version__), \
         mock.patch.object(version, "read_checkout_revision",
                           side_effect=lambda _repo: next(revisions)):
        fn = handler()
        fn(app, window)
        assert window._installed_version_stale is True
        assert window.update_notice is not None
        fn(app, window)
        assert window._installed_version_stale is False
        assert window.update_notice is None
        assert app._noticed_runtime_key is None
        fn(app, window)
    assert window._installed_version_stale is True
    assert len(messages) == 2
    assert len(headers) == 3


def test_returning_to_running_version_clears_stale_notice_without_git_metadata():
    app = SimpleNamespace(_run_revision=None, _noticed_runtime_key=None)
    window, messages = fake_window()
    disk_versions = iter(["9.9.9", version.__version__])
    with mock.patch.object(version, "read_checkout_version",
                           side_effect=lambda _path: next(disk_versions)), \
         mock.patch.object(version, "read_checkout_revision", return_value=None):
        fn = handler()
        fn(app, window)
        assert window._installed_version_stale is True
        fn(app, window)
    assert len(messages) == 1
    assert window._installed_version_stale is False
    assert window.update_notice is None
