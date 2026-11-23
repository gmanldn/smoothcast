"""The pyproject module lists stay canonical, derived and conflict-resolvable."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
import sync_pyproject as sp

SAMPLE = '''[project]
name = "x"

[tool.setuptools]
packages = ["a"]
py-modules = [
    "alpha",
    "gamma",
]

[tool.mypy]
python_version = "3.10"
files = [
    "src/b.py",
    "src/a.py",
    "src/b.py",
]
ignore_missing_imports = true
'''


def test_modules_are_derived_from_src_and_mypy_list_is_sorted_and_deduped():
    out = sp.canonical(SAMPLE, ["alpha", "beta", "gamma"])
    assert '    "alpha",\n    "beta",\n    "gamma",\n]' in out
    assert '    "src/a.py",\n    "src/b.py",\n]' in out and out.count('"src/b.py"') == 1
    assert 'python_version = "3.10"' in out and "ignore_missing_imports = true" in out
    assert sp.canonical(out, ["alpha", "beta", "gamma"]) == out            # idempotent


def test_conflicts_inside_the_lists_are_resolved_as_a_union():
    conflicted = SAMPLE.replace(
        '    "gamma",\n',
        '<<<<<<< HEAD\n    "gamma",\n    "mine",\n=======\n    "gamma",\n    "theirs",\n>>>>>>> abc (feat)\n')
    out = sp.canonical(conflicted, ["alpha", "gamma", "mine", "theirs"])
    assert "<<<<" not in out and ">>>>" not in out and "====" not in out
    assert '    "mine",\n    "theirs",\n' in out


def test_conflicts_outside_the_lists_are_refused_not_swallowed():
    conflicted = SAMPLE.replace('name = "x"', '<<<<<<< HEAD\nname = "x"\n=======\nname = "y"\n>>>>>>> b\n')
    with pytest.raises(sp.SyncError):
        sp.canonical(conflicted, ["alpha"])


def test_cli_check_and_write(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ("alpha", "beta"):
        (src / f"{name}.py").write_text("")
    config = tmp_path / "pyproject.toml"
    config.write_text(SAMPLE)
    assert sp.main(["--check", "--file", str(config), "--src", str(src)]) == 1
    assert config.read_text() == SAMPLE                                   # --check never writes
    assert sp.main(["--file", str(config), "--src", str(src)]) == 0
    assert sp.main(["--check", "--file", str(config), "--src", str(src)]) == 0
    assert '"beta",' in config.read_text() and '"gamma"' not in config.read_text()


def test_the_repository_pyproject_is_canonical():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert sp.canonical(text, sp.source_modules()) == text, \
        "run: python3 scripts/ci/sync_pyproject.py   (adds new src modules, one per line)"
