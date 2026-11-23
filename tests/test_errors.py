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
