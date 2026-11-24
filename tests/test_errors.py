"""Error catalogue (#207 slice A): complete, civil, documented, never raising."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import errors
import failure_boundary

BANNED = ("traceback", "exception", "something went wrong", "oops", "command accepted",
          "invalid request body", "device is offline", "obviously")


def _generator():
    spec = importlib.util.spec_from_file_location("gen_errors_doc", ROOT / "scripts/ci/gen_errors_doc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codes_are_stable_unique_and_well_formed():
    assert len(errors.CATALOGUE) >= 12
    for code, spec in errors.CATALOGUE.items():
        assert code == spec.code
        assert re.fullmatch(r"[a-z]+\.[a-z_]+", code), code
        assert spec.category in errors.CATEGORIES and code.startswith(spec.category + ".")
        assert spec.severity in errors.SEVERITIES


@pytest.mark.parametrize("spec", list(errors.CATALOGUE.values()), ids=lambda s: s.code)
def test_every_entry_has_civil_copy_and_steps(spec):
    assert 10 <= len(spec.message) <= 220
    assert spec.message.endswith(".")
    assert spec.steps and all(0 < len(step) <= 160 for step in spec.steps)
    text = " ".join((spec.message, *spec.steps)).lower()
    assert not any(word in text for word in BANNED)
    assert not re.search(r"(/[\w.-]+){2,}|[A-Za-z]:\\", text), "no paths in copy"
    assert spec.docs_anchor.startswith("errors-") and "_" not in spec.docs_anchor


def test_docs_are_generated_and_current():
    gen = _generator()
    assert (ROOT / "docs/ERRORS.md").read_text(encoding="utf-8") == gen.render()
    assert gen.main(["--check"]) == 0
    for spec in errors.CATALOGUE.values():
        assert f'<a id="{spec.docs_anchor}"></a>' in gen.render()


def test_describe_falls_back_and_never_raises():
    assert errors.describe(ValueError("x")).code == "internal.unexpected"
    assert errors.describe(None).code == "internal.unexpected"
    assert errors.describe(errors.SmoothCastError("cast.receiver_offline")).code == "cast.receiver_offline"
    assert errors.SmoothCastError("no.such_code").spec.code == "internal.unexpected"


def test_catalogued_errors_flow_through_the_failure_boundary():
    exc = errors.SmoothCastError("cast.receiver_offline", detail="host /home/sam/x")
    failure = failure_boundary.describe(exc)
    assert failure.message == errors.CATALOGUE["cast.receiver_offline"].message
    assert failure.steps == errors.CATALOGUE["cast.receiver_offline"].steps
    assert "/home/sam" not in failure.detail


def test_every_code_used_at_a_raise_site_is_catalogued():
    """Slice B: sites tag failures with ``code=``; a typo must fail here, not in the field."""
    import ast
    used = set()
    for path in (ROOT / "src").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "code" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str) and "." in kw.value.value:
                        used.add(kw.value.value)
    assert len(used) >= 15
    assert used <= set(errors.CATALOGUE), sorted(used - set(errors.CATALOGUE))


def test_user_facing_error_code_reaches_failure_and_recent_ring():
    from async_jobs import UserFacingError
    errors.reset_recent()
    failure = failure_boundary.describe(UserFacingError("Gone.", code="media.unavailable"))
    assert failure.code == "media.unavailable"
    assert failure.steps == errors.CATALOGUE["media.unavailable"].steps
    failure_boundary.describe(UserFacingError("Odd.", code="not.a_code"))
    failure_boundary.describe(ValueError("raw"))
    assert [e["code"] for e in errors.recent()] == [
        "media.unavailable", "internal.unexpected", "internal.unexpected"]


def test_recent_ring_is_bounded_and_diagnostics_carry_codes():
    import diagnostics
    errors.reset_recent()
    for _ in range(50):
        errors.record("cast.receiver_offline")
    assert len(errors.recent()) == 20
    assert diagnostics.collect()["error_codes"][-1]["code"] == "cast.receiver_offline"
    errors.reset_recent()


def test_preflight_and_ffmpeg_failures_carry_catalogue_codes(tmp_path):
    import ffmpeg_compat
    import preflight
    import subprocess
    exc = None
    try:
        ffmpeg_compat.require_supported_ffmpeg(run=lambda *a, **k: (_ for _ in ()).throw(OSError()))
    except ffmpeg_compat.FFmpegVersionError as caught:
        exc = caught
    assert exc and exc.code == "ffmpeg.missing"
    assert issubclass(preflight.PreflightError, ffmpeg_compat.UserFacingError)
    assert subprocess  # imported for parity with the runtime modules


def test_recent_ring_context_is_clipped_and_redacted_in_diagnostics():
    import diagnostics
    errors.reset_recent()
    home = "/home/someone"
    errors.record("cast.receiver_offline", {
        "device": "Living Room TV", "path": f"{home}/Videos/secret.mkv",
        "long": "x" * 500, "nested": {"a": 1}, **{f"k{i}": i for i in range(10)}})
    entry = errors.recent()[-1]
    assert len(entry["context"]) == 6 and "nested" not in entry["context"]
    assert len(entry["context"]["long"]) == 120
    shown = diagnostics.collect(home=home)["error_codes"][-1]
    assert home not in str(shown)
    errors.record("cast.receiver_offline")
    assert "context" not in errors.recent()[-1]
    errors.reset_recent()
