#!/usr/bin/env python3
"""Static UX copy guard for displayed messages; no GTK imports or network."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ERROR_TYPES = frozenset({
    "PortalRequestError", "CommandError", "UploadError", "RoomError", "MediaError", "ScreenError",
})
MESSAGE_CALLS = {
    "toast": "toast", "_set_chip": "toast", "set_text": "description",
    "set_label": "description", "set_title": "title", "set_subtitle": "description",
}
GTK_LABELS = {
    "Gtk.Label": "description", "Gtk.Label.new": "description",
    "Gtk.Button": "title", "Gtk.Button.new_with_label": "title",
    "Gtk.CheckButton": "title", "Gtk.CheckButton.new_with_label": "title",
    "Gtk.ToggleButton": "title", "Gtk.ToggleButton.new_with_label": "title",
}
EXCEPTION_NAMES = frozenset({"exc", "error", "exception"})
DYNAMIC = "\0"
BANNED = (
    "command accepted", "invalid request body", "device is offline",
    "stop the current cast before changing tv",
    "this control session has expired; refresh the dashboard",
    "user error", "obviously", "something went wrong", "oops",
)
LIMITS = {"title": 90, "toast": 180, "error": 220, "description": 240}


def _message_variants(value: ast.AST) -> Iterator[ast.AST]:
    if isinstance(value, ast.IfExp):
        yield from _message_variants(value.body)
        yield from _message_variants(value.orelse)
    elif isinstance(value, ast.BoolOp):
        for option in value.values:
            yield from _message_variants(option)
    elif isinstance(value, ast.Call) and value.args and ast.unparse(value.func) in {
        "_", "gettext", "gettext.gettext",
    }:
        yield from _message_variants(value.args[0])
    else:
        yield value


def _static_texts(value: ast.AST) -> Iterator[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        yield value.value
    elif isinstance(value, ast.JoinedStr):
        yield "".join(part.value if isinstance(part, ast.Constant) else DYNAMIC
                      for part in value.values)
    elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
          and value.func.attr == "format"):
        for template in _message_variants(value.func.value):
            yield from _static_texts(template)


def _raw_exception(value: ast.AST, names: frozenset[str]) -> bool:
    if isinstance(value, ast.Name):
        return value.id in names
    if isinstance(value, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) and _raw_exception(part.value, names)
                   for part in value.values)
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id in {"str", "repr"}:
            return any(isinstance(arg, ast.Name) and arg.id in names | EXCEPTION_NAMES
                       for arg in value.args)
        if isinstance(value.func, ast.Attribute) and value.func.attr == "format":
            return any(_raw_exception(part, names) for part in
                       [*value.args, *(kw.value for kw in value.keywords)])
    return False


def _messages(call: ast.Call) -> Iterator[tuple[str, ast.AST]]:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else "")
    keywords = {kw.arg: kw.value for kw in call.keywords}
    if name == "FramePositionError" and call.args:
        yield "error", call.args[0]
        return
    if name in ERROR_TYPES:
        if "message" in keywords:
            yield "error", keywords["message"]
        elif len(call.args) >= 2:
            yield "error", call.args[1]
        return

    qualified = ast.unparse(func) if name in {
        "Label", "Button", "CheckButton", "ToggleButton", "new_with_label", "new",
    } else ""
    if qualified == "Adw.AlertDialog.new":
        for kind, argument in zip(("title", "description"), call.args):
            yield kind, argument
    elif qualified == "Adw.Toast.new" and call.args:
        yield "toast", call.args[0]
    elif qualified in GTK_LABELS:
        if "label" in keywords:
            yield GTK_LABELS[qualified], keywords["label"]
        elif call.args:
            yield GTK_LABELS[qualified], call.args[0]
    elif name in MESSAGE_CALLS and call.args:
        yield MESSAGE_CALLS[name], call.args[0]

    if "title" in keywords:
        yield "title", keywords["title"]
    if "subtitle" in keywords:
        yield "description", keywords["subtitle"]


def scan_source(source: str, *, path: str = "<source>") -> list[str]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: source could not be parsed"]
    nodes = list(ast.walk(tree))
    caught: dict[ast.Call, set[str]] = {}
    for node in nodes:
        if isinstance(node, ast.ExceptHandler) and node.name:
            for statement in node.body:
                for child in ast.walk(statement):
                    if isinstance(child, ast.Call):
                        caught.setdefault(child, set()).add(node.name)

    failures = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        prefix = f"{path}:{node.lineno}: "
        names = frozenset(caught.get(node, ()))
        for kind, message in _messages(node):
            for value in _message_variants(message):
                if _raw_exception(value, names):
                    failures.append(prefix + "raw exception shown to user")
                for text in _static_texts(value):
                    compact = " ".join(text.replace(DYNAMIC, " ").casefold().split())
                    for phrase in BANNED:
                        if phrase in compact:
                            failures.append(prefix + f"banned UX phrase {phrase!r}")
                    if len(text.replace(DYNAMIC, "")) > LIMITS[kind]:
                        failures.append(prefix + f"{kind} exceeds {LIMITS[kind]} characters")
                    if kind == "title" and text.strip().endswith("."):
                        failures.append(prefix + "title ends with a full stop")
    return list(dict.fromkeys(failures))


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
