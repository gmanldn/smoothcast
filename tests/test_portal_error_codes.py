"""#519: optional catalogue codes must survive portal HTTP and replay boundaries."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import errors  # noqa: E402
import portal  # noqa: E402
import portal_commands as commands  # noqa: E402
import portal_room  # noqa: E402
import portal_uploads  # noqa: E402


@pytest.mark.parametrize("factory", [
    portal.PortalRequestError,
    commands.CommandError,
    portal_uploads.UploadError,
    portal_room.RoomError,
])
def test_error_classes_preserve_legacy_calls_and_optional_code(factory):
    legacy = factory(409, "Original user message")
    assert legacy.status == 409 and legacy.message == str(legacy)
    assert legacy.code is None
    coded = factory(409, "Original user message", code="cast.playback_changed")
    assert coded.status == 409 and coded.message == "Original user message"
    assert coded.code == "cast.playback_changed"


def test_http_serialises_catalogue_code_without_rewording_or_forcing_code():
    captured = []
    fake = SimpleNamespace(_send=lambda status, body, **kwargs:
                           captured.append((status, body, kwargs)))
    portal._Handler._error(fake, 409, "Original user message", code="cast.playback_changed")
    assert captured[-1][0] == 409
    assert captured[-1][1] == {
        "ok": False, "error": "Original user message", "code": "cast.playback_changed",
    }
    portal._Handler._error(fake, 400, "Unmapped message")
    assert captured[-1][1] == {"ok": False, "error": "Unmapped message"}


def test_room_expiry_is_coded_and_uncatalogued_exceptions_remain_uncoded():
    room = portal_room.PortalRoom()
    with pytest.raises(portal_room.RoomError) as raised:
        room.touch("missing")
    assert raised.value.code == "room.session_expired"
    outputs = []
    handler = SimpleNamespace(_error=lambda status, message, **kwargs:
                              outputs.append((status, message, kwargs)))
    portal._Handler._exception_error(handler, raised.value)
    assert outputs[-1][2] == {"code": "room.session_expired"}
    portal._Handler._exception_error(
        handler, portal.PortalRequestError(400, "Legacy error"))
    assert outputs[-1] == (400, "Legacy error", {})


def test_stale_command_is_coded_before_actions_run():
    fence = commands.CommandFence()
    current, revision, _owner = fence.snapshot()
    with pytest.raises(commands.CommandError) as raised:
        fence.check(current, revision + 1)
    assert raised.value.status == 409
    assert raised.value.code == "cast.playback_changed"
    assert "Playback changed before your command" in raised.value.message


def test_known_upload_failures_have_stable_codes(tmp_path):
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    try:
        with pytest.raises(portal_uploads.UploadError) as raised:
            uploads.status("owner", "does-not-exist")
        assert raised.value.code == "upload.not_found"
    finally:
        uploads.close()


def test_every_catalogue_style_code_literal_exists():
    """AST-based guard for stable dotted codes; internal client schema is separate."""
    seen = set()
    for path in (ROOT / "src").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (kw.arg == "code" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                        and "." in kw.value.value):
                    seen.add(kw.value.value)
    assert seen
    assert seen <= errors.CATALOGUE.keys(), sorted(seen - errors.CATALOGUE.keys())
