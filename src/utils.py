"""Pure text helpers with no GUI toolkit dependencies."""
from __future__ import annotations

import pathlib
import re


def pretty_title(path: pathlib.Path | object) -> str:
    """Human-friendly title from a path-like object.

    Accepts anything exposing ``.stem`` and ``.name`` (pathlib.Path or a test
    double). Strips dots/underscores and trailing year tokens.
    """
    stem = re.sub(r"[._]+", " ", getattr(path, "stem", "") or "").strip()
    stem = re.sub(r"\s+(19|20)\d\d\s*$", "", stem).strip()
    return stem or getattr(path, "name", "")
