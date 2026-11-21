#!/usr/bin/env python3
"""Static UX copy guard for displayed messages; no GTK imports or network."""
from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ERROR_TYPES = frozenset({"PortalRequestError", "CommandError", "UploadError", "RoomError"})
TOAST_CALLS = frozenset({"toast", "_set_chip", "set_text", "set_label"})
TITLE_CALLS = frozenset({"set_title"})
BANNED = (
    "command accepted", "invalid request body", "device is offline",
    "stop the current cast before changing tv",
    "this control session has expired; refresh the dashboard",
    "user error", "obviously", "something went wrong", "oops",
)
LIMITS = {"title": 90, "toast": 180, "error": 220, "description": 240}


def _visible_static_text(value: ast.AST) -> str:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.JoinedStr):
        return "".join(part.value for part in value.values
                       if isinstance(part, ast.Constant) and isinstance(part.value, str))
    if isinstance(value, ast.IfExp):
        return max((_visible_static_text(value.body), _visible_static_text(value.orelse)),
                   key=len, default="")
    return ""


def _raw_exception(value: ast.AST) -> bool:
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "str" and len(value.args) == 1
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id in {"exc", "error", "exception"})


def scan_source(source: str, *, path: str = "<source>") -> list[str]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: source could not be parsed"]
    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else ""
        )
        error = name in ERROR_TYPES
        kind = "error" if error else (
            "title" if name in TITLE_CALLS else (
                "toast" if name in TOAST_CALLS else ""))
        args = node.args[1:2] if error else node.args[:1]
        for kw in node.keywords:
            if kw.arg == "title":
                args = [kw.value]
                kind = "title"
            elif kw.arg == "subtitle" and not kind:
                args = [kw.value]
                kind = "description"
        if not kind or not args:
            continue
        if kind == "toast" and _raw_exception(args[0]):
            failures.append(f"{path}:{node.lineno}: raw exception shown to user")
        text = _visible_static_text(args[0])
        if not text:
            continue  # dynamic content needs review; no optimistic pass claim
        compact = " ".join(text.casefold().split())
        for phrase in BANNED:
            if phrase in compact:
                failures.append(f"{path}:{node.lineno}: banned UX phrase {phrase!r}")
        if len(text) > LIMITS[kind]:
            failures.append(f"{path}:{node.lineno}: {kind} exceeds {LIMITS[kind]} characters")
        if kind == "title" and text.strip().endswith("."):
            failures.append(f"{path}:{node.lineno}: title ends with a full stop")
    return failures


def validate(root: Path = ROOT) -> list[str]:
    failures = []
    for file in sorted((root / "src").glob("*.py")):
        failures.extend(scan_source(file.read_text(encoding="utf-8"),
                                    path=str(file.relative_to(root))))
    return failures


def main() -> int:
    failures = validate(ROOT)
    for error in failures:
        print("COPY FAIL:", error)
    if failures:
        return 1
    print("UX COPY OK: user-facing source literals meet style limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
