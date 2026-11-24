"""GTK-free model for the failure banner: Try again / Fix it / Details / Copy diagnostics (#207).

A banner is built only from a catalogued ``UserFailure``: the stable code, the
reviewed message, the ordered remediation steps ("Fix it") and the docs anchor.
Nothing here shows an exception argument, a path or a traceback; the copied
diagnostics hold the code, the exception *type*, and the last few catalogue
codes with their already-clipped context.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import desktop_failure_notice
import errors
from failure_boundary import UserFailure, redact

RECENT_LIMIT = 5
LABELS = {"retry": "Try again", "details": "Details", "copy": "Copy diagnostics"}


@dataclass(frozen=True)
class Banner:
    code: str
    message: str
    steps: tuple[str, ...]
    severity: str
    retryable: bool
    anchor: str
    actions: tuple[tuple[str, str], ...]  # (id, label), in display order


def build(failure: UserFailure, *, can_retry: bool = False) -> Banner:
    """Banner for *failure*; **Try again** only when the code is retryable and a retry exists."""
    spec = errors.CATALOGUE.get(failure.code, errors.FALLBACK)
    ids = (["retry"] if spec.retryable and can_retry else []) + ["details", "copy"]
    return Banner(spec.code, failure.message, tuple(failure.steps or spec.steps), spec.severity,
                  spec.retryable, spec.docs_anchor, tuple((i, LABELS[i]) for i in ids))


def details_text(banner: Banner) -> str:
    """Plain-language explanation with the ordered **Fix it** steps."""
    lines = [banner.message, ""]
    if banner.steps:
        lines.append("How to fix it:")
        lines += [f"{n}. {step}" for n, step in enumerate(banner.steps, 1)]
        lines.append("")
    lines.append(f"Code: {banner.code}  (docs/ERRORS.md#{banner.anchor})")
    return "\n".join(lines)


def diagnostics_text(failure: UserFailure, recent: list[dict] | None = None,
                     limit: int = RECENT_LIMIT) -> str:
    """Safe clipboard text: code, exception type, and the last *limit* codes."""
    spec = errors.CATALOGUE.get(failure.code, errors.FALLBACK)
    lines = [desktop_failure_notice.copy_details(replace(failure, code=spec.code)),
             f"Category: {spec.category}\nSeverity: {spec.severity}\nRetryable: {spec.retryable}"]
    history = (errors.recent() if recent is None else recent) if limit > 0 else []
    if history:
        lines.append("Recent error codes (oldest first):")
        for entry in history[-limit:]:
            code = entry.get("code") if isinstance(entry, dict) else None
            if code not in errors.CATALOGUE:
                continue
            context = entry.get("context") or {}
            facts = ", ".join(f"{k}={redact(str(v))}" for k, v in sorted(context.items()))
            lines.append(f"- {code}" + (f" ({facts})" if facts else ""))
    return "\n".join(lines)
