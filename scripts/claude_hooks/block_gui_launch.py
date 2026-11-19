#!/usr/bin/env python3
"""Claude Code PreToolUse hook: refuse Bash commands that open SmoothCast's GUI.

AGENTS.md forbids launching the real window during development because it
steals the user's desktop focus and can control their TV. Instructions are only
advisory context, so this hook enforces the rule deterministically.

Protocol (Claude Code hooks): the tool call arrives as JSON on stdin; exit code
2 blocks the call and returns stderr to the agent; any other exit allows it.

This is a guard against accidents, not a security boundary. It fails open: a
command it cannot parse is allowed. Pure stdlib; never imports GTK.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

# Arguments after which the launcher exits without opening a window.
SAFE_FIRST_ARGS = frozenset({
    "--version", "-V", "--help", "-h", "--diagnostics", "--network-check",
    "--library-index",
})
LAUNCHERS = frozenset({"smoothcast", "smoothcast-gui"})
GUI_SCRIPTS = frozenset({"sc.py", "cast_control.py", "cli.py", "launch.py"})
GUI_MODULES = frozenset({"cast_control", "cli", "launch"})
WRAPPERS = frozenset({"sudo", "env", "time", "nohup", "exec", "command", "setsid"})
# Wrapper options that consume the following word, so it is not the command.
WRAPPER_OPTIONS_WITH_VALUE = {
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"),
    "env": ("-u", "-C", "-S"),
    "time": ("-f", "-o"),
}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = re.compile(r"&&|\|\||[;|&\n]")
_PYTHON = re.compile(r"python(\d+(\.\d+)*)?(\.exe)?\Z")

MESSAGE = (
    "Blocked: this command would launch the real SmoothCast GUI, which steals "
    "the user's desktop focus and may control their TV (see AGENTS.md, 'Testing "
    "— no desktop focus'). Run `python3 -m pytest -q tests` instead, or the "
    "isolated smoke test `python3 scripts/test_gui_isolated.py`."
)


def _words(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return []  # unbalanced quotes etc.: fail open
    wrapper = ""
    while tokens:
        head = tokens[0]
        if _ASSIGNMENT.match(head):
            tokens.pop(0)
        elif head in WRAPPERS:
            wrapper = tokens.pop(0)
        elif wrapper and head.startswith("-") and len(tokens) > 1:
            tokens.pop(0)
            if head in WRAPPER_OPTIONS_WITH_VALUE.get(wrapper, ()):
                tokens.pop(0)  # e.g. the user name after `sudo -u`
        else:
            break
    return tokens


def _launches_gui(tokens: list[str]) -> bool:
    if not tokens:
        return False
    name = os.path.basename(tokens[0])
    args = tokens[1:]
    if name == "gtk-launch":
        return True
    if name in LAUNCHERS:
        return not (args and args[0] in SAFE_FIRST_ARGS)
    if _PYTHON.match(name):
        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "-m" and index + 1 < len(args):
                target, rest = args[index + 1], args[index + 2:]
                return target in GUI_MODULES and not (rest and rest[0] in SAFE_FIRST_ARGS)
            if arg.startswith("-"):
                index += 1
                continue
            rest = args[index + 1:]
            return (os.path.basename(arg) in GUI_SCRIPTS
                    and not (rest and rest[0] in SAFE_FIRST_ARGS))
    return False


def decide(command: str) -> str | None:
    """Return a refusal message for a GUI-launching command, else None."""
    for segment in _SEPARATORS.split(command):
        if _launches_gui(_words(segment.strip())):
            return MESSAGE
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
    except (ValueError, KeyError, TypeError):
        return 0  # not a Bash payload we understand: allow
    if not isinstance(command, str):
        return 0
    refusal = decide(command)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
