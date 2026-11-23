"""CI traceability checker rejects missing test evidence without importing GTK."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_check_invariants", ROOT / "scripts" / "ci" / "check_invariants.py",
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_every_documented_invariant_has_an_existing_asserting_pytest_guard():
    assert checker.validate(ROOT) == []


def _fixture(tmp_path):
    root = tmp_path
    for folder in ("docs/agents", "src", "tests"):
        (root / folder).mkdir(parents=True)
    (root / "docs/agents/architecture.md").write_text(
        "## Safety\n<!-- invariant: INV-999 -->\n", encoding="utf-8"
    )
    (root / "docs/INVARIANTS.md").write_text(
        "| ID | Safety invariant | Owner module | Guarding pytest node ID |\n"
        "| --- | --- | --- | --- |\n"
        "| INV-999 | A required test exists | src/guard.py | tests/test_guard.py::test_guard |\n",
        encoding="utf-8",
    )
    (root / "src/guard.py").write_text("def check():\n    return True\n", encoding="utf-8")
    (root / "tests/test_guard.py").write_text(
        'def test_guard():\n    """INV-999: observed guard"""\n    assert True\n',
        encoding="utf-8",
    )
    return root


def test_missing_tests_or_assertions_are_never_marked_as_qualified(tmp_path):
    root = _fixture(tmp_path)
    assert checker.validate(root) == []
    guard = root / "tests/test_guard.py"
    guard.write_text('def test_guard():\n    """INV-999: observed guard"""\n    pass\n')
    assert any("no direct assertion" in err for err in checker.validate(root))
    guard.unlink()
    assert any("test unavailable" in err for err in checker.validate(root))


def test_guard_docstring_and_architecture_marker_are_bidirectional(tmp_path):
    root = _fixture(tmp_path)
    guard = root / "tests/test_guard.py"
    guard.write_text('def test_guard():\n    """Someone moved the test"""\n    assert True\n')
    assert any("docstring" in err for err in checker.validate(root))
    (root / "docs/agents/architecture.md").write_text("## No marker\n")
    errors = checker.validate(root)
    assert any("matrix row has no architecture marker" in err for err in errors)


def test_checker_ignores_missing_unqualified_rows_but_requires_nonempty_manifest(tmp_path):
    root = _fixture(tmp_path)
    (root / "docs/INVARIANTS.md").write_text("| ID | Guard |\n")
    assert any("no guard rows" in err for err in checker.validate(root))
    assert any("architecture marker has no matrix row" in err for err in checker.validate(root))
