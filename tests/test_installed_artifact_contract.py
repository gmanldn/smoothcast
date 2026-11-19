"""Installed-wheel source contract without spawning GTK or build tools."""
from __future__ import annotations

import ast

from pathlib import Path
import importlib.util
import os
import sys
from unittest import mock

import smoothcast_assets
import streamer
import server
import version


ROOT = Path(__file__).resolve().parents[1]


def test_every_python_source_module_is_declared_for_wheel_install():
    # Cheap Python 3.10+ gate: fail early when a new module is added in src/
    # but omitted from explicit setuptools py-modules (e.g. cast_targets).
    # Wheel matrix independently checks the actual built artifact.
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "py-modules = [" in config
    values = config.split("py-modules = [", 1)[1].split("]", 1)[0]
    declared = set(ast.literal_eval("[" + values + "]"))
    actual = {
        path.stem for path in (ROOT / "src").glob("*.py")
        if path.name != "__init__.py"
    }
    assert declared == actual, (
        f"Missing modules: {sorted(actual - declared)}; "
        f"Nonexistent declarations: {sorted(declared - actual)}"
    )
    assert "cast_targets" in declared
    assert "watch_history" in declared


def test_source_icon_is_identical_to_canonical_artwork():
    installed = smoothcast_assets.icon_path()
    original = ROOT / "data" / "cast-control.png"
    assert installed.name == "local.cast-control.png"
    assert installed.parent.name == "smoothcast_assets"
    assert installed.read_bytes() == original.read_bytes()
    assert installed.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_wheel_declares_package_data_instead_of_checkout_asset_path():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["smoothcast_assets"]' in text
    assert 'smoothcast_assets = ["local.cast-control.png"]' in text
    gui_source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert "import smoothcast_assets" in gui_source
    assert "smoothcast_assets.icon_path()" in gui_source
    assert '_data_dir = pathlib.Path(__file__).resolve().parent.parent / "data"' not in gui_source


def test_hls_server_is_installed_as_local_python_module():
    assert "server" in (ROOT / "pyproject.toml").read_text()
    assert streamer.SERVER_SCRIPT.is_file()
    assert streamer.SERVER_SCRIPT.samefile(Path(server.__file__))
    assert server.public_resource("/movie.m3u8")
    assert server.public_resource("/segment-00002.ts")
    assert not server.public_resource("/session.json")


def _check_module():
    path = ROOT / "scripts" / "ci" / "verify_installed_artifact.py"
    spec = importlib.util.spec_from_file_location("artifact_ci", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_builds_wheel_from_sdist_not_checkout_and_scrubs_desktop():
    source = (ROOT / "scripts" / "ci" /
              "verify_installed_artifact.py").read_text()
    assert '"--sdist", "--no-isolation"' in source
    assert '"pip", "wheel", "--no-deps"' in source
    assert "str(archives[0])" in source
    assert "str(artifacts[0])" in source
    assert "outside checkout with spaces" in source
    assert 'python), "-I", "-c", VERIFY' in source
    assert 'import smoothcast_assets' in source
    assert 'assert helper.is_file()' in source
    assert 'assert "gi" not in sys.modules' in source
    assert "expected_modules = sorted(p.stem" in source
    assert 'metadata["tool"]["setuptools"]["py-modules"]' in source
    assert "importlib.util.find_spec(name)" in source
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text()
    assert "installed-artifact:" in workflow
    assert "python scripts/ci/verify_installed_artifact.py" in workflow
    for platform in ("ubuntu-24.04", "macos-15", "windows-2025"):
        assert platform in workflow


def test_ci_clean_environment_removes_checkout_and_display_inheritance():
    module = _check_module()
    dirty = {
        "PYTHONPATH": "/untrusted/checkout/src",
        "PYTHONHOME": "/untrusted",
        "VIRTUAL_ENV": "/my/venv",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "DBUS_SESSION_BUS_ADDRESS": "session-bus",
        "XAUTHORITY": "/tmp/xauth",
        "PATH": os.environ.get("PATH", ""),
    }
    with mock.patch.dict(module.os.environ, dirty, clear=True):
        clean = module.clean_environment()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
                "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                "XAUTHORITY"):
        assert key not in clean
    assert clean["SMOOTHCAST_TEST_CONTEXT"] == "1"
    assert clean["PYTHONNOUSERSITE"] == "1"
    assert clean["PATH"] == dirty["PATH"]


def test_installed_gui_launcher_is_not_invoked_during_source_tests():
    # CI only invokes --version; GTK launch remains explicitly prohibited.
    source = (ROOT / "scripts" / "ci" /
              "verify_installed_artifact.py").read_text()
    assert '[str(entry), "--version"]' in source
    assert "smoothcast-gui" in source
    assert "gtk-launch" not in source
