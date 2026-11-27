"""Top-level module names must not shadow the stdlib or well-known packages (#107)."""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generic names that already ship; the list may only shrink (move into a package).
GENERIC_ALLOWED = {"cli", "errors", "server", "utils", "version"}
GENERIC_RISKY = GENERIC_ALLOWED | {
    "config", "util", "common", "helpers", "state", "models", "app", "main", "core",
    "test", "tests", "setup", "types", "typing_extensions", "six", "attr", "yaml",
    "requests", "gi", "dbus", "numpy", "click", "rich", "jinja2", "flask"}


def _modules():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return set(data["tool"]["setuptools"]["py-modules"])


def test_no_module_shadows_stdlib():
    assert sorted(_modules() & set(sys.stdlib_module_names)) == []


def test_no_new_generic_top_level_names():
    new = _modules() & GENERIC_RISKY - GENERIC_ALLOWED
    assert not new, f"generic top-level names collide with other distributions: {sorted(new)}"


def test_allowlist_has_no_stale_entries():
    assert GENERIC_ALLOWED <= _modules(), "remove names already moved into a package"
