"""Snapshot redaction by role and sharing level (#329). Pure; applied before serialisation.

Levels: ``full`` (titles shown), ``hidden`` (titles replaced by a neutral
label, ids stay stable for collaboration). Host-only keys and anything that
looks like a path, credential-bearing URL or the host user name is stripped
for every non-host role at every depth, regardless of level.
"""
from __future__ import annotations

import re

LEVELS = ("full", "hidden")
HOST_ONLY = {"path", "file", "filepath", "dir", "folder", "history", "recent", "diagnostics",
             "user", "username", "token", "secret", "pin", "csrf", "password", "url_credentials"}
TITLE_KEYS = {"title", "name", "filename", "subtitle", "artist", "album"}
_PATH = re.compile(r"(^|[\s\"'(])(/(?:home|Users|root|tmp|mnt|media|var)/|[A-Za-z]:\\)")
_CRED_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]*@", re.I)
HIDDEN_TITLE = "Hidden item"


def _clean_str(value: str, user: str) -> str:
    if _CRED_URL.search(value):
        value = _CRED_URL.sub(lambda m: m.group(0).split("://")[0] + "://", value)
    if _PATH.search(value):
        return "[hidden]"
    if user and user in value:
        value = value.replace(user, "[user]")
    return value


def redact(snapshot, role: str, level: str = "full", user: str = ""):
    """Deep copy of ``snapshot`` safe for ``role``. Host receives it unchanged."""
    if role == "host":
        return snapshot
    hide = level == "hidden" or level not in LEVELS     # unknown level fails closed
    return _walk(snapshot, hide, user)


def _walk(node, hide: bool, user: str):
    if isinstance(node, dict):
        out = {}
        for key, val in node.items():
            k = str(key).lower()
            if k in HOST_ONLY:
                continue
            if hide and k in TITLE_KEYS and isinstance(val, str):
                out[key] = HIDDEN_TITLE
            else:
                out[key] = _walk(val, hide, user)
        return out
    if isinstance(node, (list, tuple)):
        return [_walk(v, hide, user) for v in node]
    if isinstance(node, str):
        return _clean_str(node, user)
    return node


def leaks(payload: str, canaries: list[str]) -> list[str]:
    """Canary check for tests: which secrets appear in a serialised response."""
    return [c for c in canaries if c and c in payload]
