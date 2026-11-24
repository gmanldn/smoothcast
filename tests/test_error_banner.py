"""Headless contract for the failure banner model (#207); no GTK."""
from __future__ import annotations

from pathlib import Path

import pytest

import error_banner
import errors
import failure_boundary

ROOT = Path(__file__).resolve().parents[1]


def _failure(code, detail="OSError: /home/sam/secret/film.mkv: token=abc123"):
    spec = errors.CATALOGUE[code]
    return failure_boundary.UserFailure(spec.message, spec.steps, detail, True, code)


@pytest.mark.parametrize("code", sorted(errors.CATALOGUE))
def test_every_catalogued_code_builds_a_banner_with_details_and_a_documented_anchor(code):
    banner = error_banner.build(_failure(code))
    assert banner.code == code and banner.steps and banner.message
    text = error_banner.details_text(banner)
    assert "How to fix it:" in text and "1. " in text and f"Code: {code}" in text
    assert f'id="{banner.anchor}"' in (ROOT / "docs" / "ERRORS.md").read_text(encoding="utf-8")
    ids = [action for action, _ in banner.actions]
    assert ids[-2:] == ["details", "copy"] and "retry" not in ids


def test_try_again_needs_both_a_retryable_code_and_a_retry_action():
    retryable = next(c for c, s in errors.CATALOGUE.items() if s.retryable)
    fixed = next(c for c, s in errors.CATALOGUE.items() if not s.retryable)
    labels = lambda banner: [label for _id, label in banner.actions]  # noqa: E731
    assert labels(error_banner.build(_failure(retryable), can_retry=True)) == [
        "Try again", "Details", "Copy diagnostics"]
    assert "Try again" not in labels(error_banner.build(_failure(retryable)))
    assert "Try again" not in labels(error_banner.build(_failure(fixed), can_retry=True))


def test_unknown_code_falls_back_to_the_internal_entry():
    banner = error_banner.build(failure_boundary.UserFailure("Oops. Retry.", ("Retry.",), "", False, "nope.nothing"))
    assert banner.code == errors.FALLBACK.code


def test_copied_diagnostics_hold_codes_and_type_but_no_arguments_paths_or_tokens():
    code = "cast.receiver_offline"
    text = error_banner.diagnostics_text(_failure(code), recent=[
        {"at": 1, "code": "media.unavailable", "context": {"file": "/home/sam/private/a.mkv"}},
        {"at": 2, "code": "not.a.code"}, {"at": 3, "code": code}])
    assert "Code: cast.receiver_offline" in text and "Exception type: OSError" in text
    assert "- media.unavailable (file=.../a.mkv)" in text and "not.a.code" not in text
    for secret in ("secret", "film.mkv", "abc123", "/home/sam/private"):
        assert secret not in text
    assert "Traceback" not in text


def test_recent_history_is_bounded_to_the_last_few_codes():
    history = [{"at": n, "code": "media.unavailable"} for n in range(50)]
    text = error_banner.diagnostics_text(_failure("media.unavailable"), recent=history, limit=3)
    assert text.count("- media.unavailable") == 3


def test_ui_glue_never_touches_tracebacks_or_exception_arguments():
    source = (ROOT / "src" / "error_banner_ui.py").read_text(encoding="utf-8")
    import re
    assert "traceback" not in source and not re.search(r"failure\.detail\b", source)
