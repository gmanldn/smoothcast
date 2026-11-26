"""Chaos scenarios: no traceback, source path or secret reaches the UI (#207).

Every text a user can see or copy (toast message, details dialog, diagnostics,
cast-failure console code) is built from hostile exceptions and checked."""
from __future__ import annotations

import re

import pytest

import cast_failure_code
import error_banner
import errors
import failure_boundary

SECRET = "token=hunter2"
LEAKS = re.compile(r"Traceback|File \"|\bline \d|/home/|hunter2|site-packages|\.py\b")


def _boom(factory):
    try:
        factory()
    except BaseException as exc:  # noqa: BLE001 - chaos harness captures everything
        return exc
    raise AssertionError("factory did not raise")


def _chain():
    try:
        raise OSError(f"/home/sam/secret/film.mkv: {SECRET}")
    except OSError as inner:
        raise RuntimeError(f"wrapped /home/sam/app/cast_session.py {SECRET}") from inner


SCENARIOS = {
    "oserror_path": lambda: (_ for _ in ()).throw(OSError(f"/home/sam/x.mkv {SECRET}")),
    "keyerror": lambda: {}["missing"],
    "zerodiv": lambda: 1 / 0,
    "attr": lambda: None.nope,
    "chained": _chain,
    "unicode": lambda: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"\xff", 0, 1, SECRET)),
    "recursion": lambda: (_ for _ in ()).throw(RecursionError(SECRET)),
    "smoothcast_code": lambda: (_ for _ in ()).throw(
        errors.SmoothCastError("cast.receiver_offline", detail=f"/home/sam/a.py {SECRET}")),
    "unknown_code": lambda: (_ for _ in ()).throw(
        errors.SmoothCastError("made.up_code", detail=SECRET)),
    "str_with_traceback": lambda: (_ for _ in ()).throw(
        RuntimeError("Traceback (most recent call last):\n  File \"/home/sam/a.py\", line 3")),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_user_visible_text_is_traceback_free(name):
    errors.reset_recent()
    exc = _boom(SCENARIOS[name])
    failure = failure_boundary.describe(exc)
    banner = error_banner.build(failure, can_retry=True)
    shown = [failure.message, banner.message, error_banner.details_text(banner),
             error_banner.diagnostics_text(failure), *banner.steps]
    for text in shown:
        assert not LEAKS.search(text), (name, text)


@pytest.mark.parametrize("message", [
    "Receiver is offline", "probe timed out", "Traceback (most recent call last): boom",
    f"/home/sam/film.mkv failed {SECRET}", "", None, 12345, "x" * 5000])
def test_cast_failure_code_is_catalogued_and_keeps_no_raw_text(message):
    errors.reset_recent()
    code = cast_failure_code.note(message)
    assert code in errors.CATALOGUE
    history = errors.recent()
    assert [entry["code"] for entry in history] == [code]
    assert str(history).find("Traceback") < 0 and SECRET not in str(history)
    assert "home" not in str(history)


def test_cast_failure_code_classifies_known_wording_and_falls_back():
    assert cast_failure_code.note("Receiver is offline") == "cast.receiver_offline"
    assert cast_failure_code.note("something odd") == cast_failure_code.FALLBACK
