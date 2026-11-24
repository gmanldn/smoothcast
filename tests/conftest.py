"""Fail-closed test environment: never connect GTK to the user's session.

Ordinary pytest is entirely headless. Clear inherited display/session channels
*before* collection, so even an accidental direct PyGObject import cannot
connect to the user's running Wayland/X11 desktop or D-Bus session.

Only the separate opt-in scripts/test_gui_isolated.py may create GTK windows,
and it supplies its own disposable Xvfb session and credentials.
"""
from __future__ import annotations

import os
import tempfile

os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"
# Never read or write a developer's real home: settings (hls_port, cache_cap_mb),
# the cache dir (session.json, server.log) and the error log all live under HOME.
# Set before any test imports modules that compute paths from Path.home().
_HOME = tempfile.mkdtemp(prefix="smoothcast-test-home-")
# Opt-in browser smoke tests need the developer's installed Playwright browsers,
# which live under the real HOME; point at them (read-only) before HOME is swapped.
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    _real_pw = os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
        "ms-playwright")
    if os.path.isdir(_real_pw):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _real_pw
os.environ["HOME"] = _HOME
os.environ["XDG_CONFIG_HOME"] = os.path.join(_HOME, ".config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_HOME, ".cache")
os.environ["XDG_DATA_HOME"] = os.path.join(_HOME, ".local", "share")
os.environ["GDK_BACKEND"] = "x11"  # No X11 server without DISPLAY.
for name in (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
    "SMOOTHCAST_GUI_TEST_ISOLATED",
):
    os.environ.pop(name, None)


import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

# Only this module exercises the real FFmpeg version probe (#242).
_REAL_FFMPEG_PROBE_MODULES = {"test_ffmpeg_version_guard"}


@pytest.fixture(autouse=True)
def _stub_ffmpeg_version_probe(request):
    """Tests that mock subprocesses must not hit the real ``ffmpeg -version`` probe.

    ``Session.start_transcode`` now verifies the FFmpeg version first (a
    subprocess). Tests that drive it with a mocked ``Popen`` would otherwise
    depend on whether the machine has a compatible ffmpeg and on how Popen is
    mocked, so the probe is stubbed everywhere except its own tests.
    """
    if request.module.__name__ in _REAL_FFMPEG_PROBE_MODULES:
        yield
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        import streamer
    except ImportError:
        yield
        return
    with mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)):
        yield


def pytest_collection_modifyitems(config, items):
    """Skip documented per-platform gaps (tests/platform_gaps.py), by exact id."""
    import sys

    import pytest

    from platform_gaps import GAPS

    gaps = GAPS.get(sys.platform, {})   # Linux has no entries: it skips nothing
    for item in items:
        reason = gaps.get(item.nodeid.split("tests/", 1)[-1])
        if reason:
            item.add_marker(pytest.mark.skip(
                reason=f"known {sys.platform} gap (#258): {reason}"))
