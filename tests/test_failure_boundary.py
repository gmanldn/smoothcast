"""Failure boundary (#512): civil messages, bounded notifications, no tracebacks."""
from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import async_jobs
import cli
import failure_boundary as fb
import portal
from test_portal import PIN, PortalRig, decode


def test_unknown_exception_is_civil_and_hides_the_cause():
    failure = fb.describe(RuntimeError("socket 10.0.0.9 exploded"))
    assert failure.title == fb.TITLE
    assert "exploded" not in failure.message and "Traceback" not in failure.message
    assert failure.message.startswith("SmoothCast hit an unexpected problem. ")
    assert "RuntimeError" in failure.detail
    assert len(failure.message) <= fb.MAX_MESSAGE


def test_reviewed_copy_is_shown_and_detail_stays_private():
    exc = async_jobs.UserFacingError("Receiver offline. Check its power and network connection.",
                                     detail="ECONNREFUSED 10.0.0.4")
    failure = fb.describe(exc)
    assert failure.message == "Receiver offline. Check its power and network connection."
    assert "10.0.0.4" in failure.detail


def test_paths_are_redacted_in_detail():
    home = str(Path.home())
    text = fb.describe(OSError(f"cannot read {home}/Videos/holiday.mkv and /etc/passwd")).detail
    assert home not in text and "/Videos/" not in text and "/etc/" not in text
    assert ".../holiday.mkv" in text
    win = fb.describe(OSError(r"bad C:\Users\sam\Movies\film.mp4")).detail
    assert "Users" not in win and ".../film.mp4" in win


def test_cause_chain_is_summarised_and_describe_never_raises():
    try:
        try:
            raise KeyError("inner")
        except KeyError as inner:
            raise ValueError("outer") from inner
    except ValueError as exc:
        detail = fb.describe(exc).detail
    assert detail.index("ValueError") < detail.index("KeyError")

    class Hostile(Exception):
        def __str__(self):
            raise RuntimeError("no str")

    assert fb.describe(Hostile()).title == fb.TITLE
    assert fb.describe(None).title == fb.TITLE
    assert len(fb.describe(RuntimeError("x" * 5000)).detail) <= fb.MAX_DETAIL


def test_notifier_collapses_a_flood_and_bounds_distinct_failures():
    now = [0.0]
    notifier = fb.Notifier(clock=lambda: now[0])
    same = fb.describe(RuntimeError("boom"))
    assert sum(notifier.allow(same) for _ in range(1000)) == 1
    now[0] = 31.0
    assert notifier.allow(same)
    now[0] = 32.0
    kinds = [fb.describe(exc) for exc in (KeyError("a"), IndexError("b"), TypeError("c"), OSError("d"))]
    assert [notifier.allow(k) for k in kinds] == [True, False, False, False]  # 3 per minute incl. `same` twice
    now[0] = 200.0
    assert notifier.allow(kinds[1])


def test_notifier_memory_is_bounded():
    now = [0.0]
    notifier = fb.Notifier(clock=lambda: now[0], per_window=10_000)
    for index in range(500):
        now[0] += 31.0
        notifier.allow(fb.UserFailure(f"t{index}", (), "X: y"))
    assert len(notifier._last) <= fb.MAX_KEYS


# ------------------------------------------------------------------ portal

@pytest.fixture
def rig():
    value = PortalRig()
    yield value
    value.close()


def login(rig):
    status, body, headers = rig.request(
        "POST", "/api/login", {"pin": PIN, "name": "Sam"}, origin=f"http://{rig.host}")
    assert status == 200, body
    cookie = headers["Set-Cookie"].split(";")[0]
    return cookie, decode(body)["csrf"]


def test_portal_handler_crash_returns_civil_json_not_a_traceback(rig):
    cookie, _csrf = login(rig)
    with mock.patch.object(rig.server.room, "snapshot", side_effect=RuntimeError("secret /home/sam/x")), \
            mock.patch("error_log.log") as log:
        status, body, headers = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    payload = decode(body)
    assert payload["ok"] is False and payload["code"] == "unexpected_error"
    text = body.decode()
    assert "Traceback" not in text and "secret" not in text and "/home/sam" not in text
    assert payload["error"].startswith("SmoothCast hit an unexpected problem.")
    assert log.call_count == 1 and "/home/sam" not in log.call_args[0][0]


def test_repeating_portal_fault_is_logged_once(rig):
    cookie, _csrf = login(rig)
    with mock.patch.object(rig.server.room, "snapshot", side_effect=RuntimeError("boom")), \
            mock.patch("error_log.log") as log:
        statuses = [rig.request("GET", "/api/status", cookie=cookie)[0] for _ in range(6)]
    assert statuses == [500] * 6
    assert log.call_count == 1


def test_portal_keeps_serving_after_a_crash(rig):
    cookie, _csrf = login(rig)
    with mock.patch.object(rig.server.room, "snapshot", side_effect=RuntimeError("boom")), \
            mock.patch("error_log.log"):
        assert rig.request("GET", "/api/status", cookie=cookie)[0] == 500
    assert rig.request("GET", "/api/status", cookie=cookie)[0] == 200


def test_every_mutating_method_is_guarded():
    for name in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
        assert getattr(portal._Handler, name).__wrapped__ is not None, name


# --------------------------------------------------------------------- CLI

def test_cli_unexpected_error_prints_one_civil_line_and_exits_1(capsys):
    with mock.patch.object(cli, "_main", side_effect=RuntimeError("boom /home/sam/film.mkv")), \
            mock.patch("error_log.log"):
        assert cli.main() == 1
    err = capsys.readouterr().err
    assert "SmoothCast hit an unexpected problem." in err
    assert "Traceback" not in err and "boom" not in err and "/home/sam" not in err


def test_cli_passes_through_system_exit_and_interrupt():
    with mock.patch.object(cli, "_main", side_effect=SystemExit(2)):
        with pytest.raises(SystemExit):
            cli.main()
    with mock.patch.object(cli, "_main", side_effect=KeyboardInterrupt):
        assert cli.main() == 130


def test_cli_still_survives_a_broken_error_log(capsys):
    with mock.patch.object(cli, "_main", side_effect=RuntimeError("boom")), \
            mock.patch("error_log.log", side_effect=OSError("disk full")):
        assert cli.main() == 1
    assert "private error log" not in capsys.readouterr().err


@pytest.mark.parametrize(("method", "path", "body", "target"), [
    ("GET", "/api/status", None, "_authenticated"),
    ("POST", "/api/action", {"action": "pause"}, "_authenticated"),
    ("PUT", "/api/uploads/abc/0", None, "_authenticated"),
    ("DELETE", "/api/uploads/abc", None, "_authenticated"),
    ("GET", "/screen", None, "_safe_origin"),
    ("POST", "/api/login", {"pin": PIN, "name": "Sam"}, "_safe_origin"),
])
def test_every_route_family_answers_a_crash_with_civil_json(rig, method, path, body, target):
    """An exception in any method/route family never reaches the client raw (#512)."""
    cookie, csrf = login(rig)
    kwargs = {"cookie": cookie}
    if method != "GET":
        kwargs["csrf"] = csrf
    with mock.patch.object(portal._Handler, target, side_effect=RuntimeError("secret /home/sam/x")), \
            mock.patch("error_log.log") as log:
        status, data, headers = rig.request(method, path, body, origin=f"http://{rig.host}", **kwargs)
    text = data.decode("utf-8", "replace")
    assert status == 500, (method, path, status, text[:120])
    assert headers["Content-Type"].startswith("application/json")
    assert "Traceback" not in text and "secret" not in text and "/home/sam" not in text
    assert decode(data)["code"] == "unexpected_error"
    assert log.call_count == 1 and "/home/sam" not in log.call_args[0][0]


def test_catalogued_code_without_reviewed_copy_uses_safe_catalogue():
    import errors

    class CodedError(RuntimeError):
        code = "cast.receiver_offline"

    errors.reset_recent()
    try:
        failure = fb.describe(CodedError("private receiver details"))
        spec = errors.CATALOGUE[CodedError.code]
        assert failure.code == spec.code
        assert failure.message == spec.message
        assert failure.steps == spec.steps
        assert "private receiver details" not in failure.message
        assert errors.recent()[-1]["code"] == spec.code
    finally:
        errors.reset_recent()


def test_unknown_code_without_reviewed_copy_still_uses_generic_failure():
    class UnknownError(RuntimeError):
        code = "cast.not_a_real_code"

    failure = fb.describe(UnknownError("private details"))
    assert failure.code == "internal.unexpected"
    assert failure.title == fb.TITLE
    assert "private details" not in failure.message
