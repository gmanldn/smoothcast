"""Resolve package metadata without importing the application during build."""
import ast
from pathlib import Path

from setuptools import setup


def release_version() -> str:
    source = Path(__file__).resolve().parent / "src" / "version.py"
    parts: dict[str, int] = {}
    names = ("MAJOR", "MINOR", "PATCH")
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        value = ast.literal_eval(node.value)
        if target.id in parts or type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise ValueError(f"Invalid canonical version component: {target.id}")
        parts[target.id] = value
    if set(parts) != set(names):
        raise ValueError("Canonical version components missing")
    return ".".join(str(parts[name]) for name in names)


setup(version=release_version())
