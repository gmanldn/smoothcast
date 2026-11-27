"""Pseudo-localisation (#219): expose hard-coded, clipped and un-translatable text.

``pseudo(text)`` accents letters, pads ~40% for longer languages and brackets the
result, while leaving printf/format placeholders (``%s``, ``%(name)s``, ``{x}``)
untouched so formatted strings still work. ``rtl(text)`` wraps in bidi controls
for right-to-left smoke tests. Pure and deterministic.
"""
from __future__ import annotations

import re

_MAP = str.maketrans(
    "AEIOUaeiouCcNnYySs",
    "ÀÉÎÕÜàéîõüÇçÑñÝÿŠš")
_PLACEHOLDER = re.compile(r"%\([^)]*\)[#0\- +]*\d*(?:\.\d+)?[sdifr]|%[#0\- +]*\d*(?:\.\d+)?[sdifr%]|\{[^{}]*\}")
RLE, PDF = "‫", "‬"


def pseudo(text: str, expand: float = 0.4) -> str:
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out, last = [], 0
    for match in _PLACEHOLDER.finditer(text):
        out.append(text[last:match.start()].translate(_MAP))
        out.append(match.group(0))
        last = match.end()
    out.append(text[last:].translate(_MAP))
    body = "".join(out)
    pad = "~" * max(1, round(len(text) * max(0.0, min(expand, 2.0))))
    return f"[{body}{pad}]"


def rtl(text: str) -> str:
    return f"{RLE}{text}{PDF}" if isinstance(text, str) else ""
