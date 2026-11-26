"""Catalogue code for a legacy plain-string cast failure (#207).

Cast failures arrive as free text from worker threads. The code is observed
only: it feeds the diagnostics history and the console line, and never changes
what the user is shown or the retry path."""
from __future__ import annotations

import cast_recovery
import errors

FALLBACK = "cast.command_failed"


def note(message: object) -> str:
    """Record the failure's catalogue code (no raw text kept) and return it."""
    try:
        code = cast_recovery.classify_message(message if isinstance(message, str) else None)
        code = code if code in errors.CATALOGUE else FALLBACK
        errors.record(code, {"stage": "cast"})
        return code
    except Exception:  # noqa: BLE001 - observation must never break failure handling
        return FALLBACK
