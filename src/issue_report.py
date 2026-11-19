"""Prefilled GitHub bug-report URL for Help > Report a problem (issue #274).

GTK-free and side-effect free: it only *builds* a URL. The app opens it in the
user's browser; nothing is sent automatically and no diagnostics are embedded
(the form asks the user to attach the redacted bundle themselves). Only the
SmoothCast version and a coarse operating-system label are prefilled: no paths,
addresses, device names or media titles.
"""
from __future__ import annotations

import platform
import re
import sys
from urllib.parse import urlencode

REPO = "gmanldn/smoothcast"
TEMPLATE = "bug-report.yml"  # blank issues are disabled, so a template is required
BASE_URL = f"https://github.com/{REPO}/issues/new"
MAX_FIELD = 120
MAX_URL = 1800  # well under common browser/server limits
_UNSAFE = re.compile(r"[^\w .+()/:,-]")


def _clean(value: object) -> str:
    """One short printable line with only harmless characters."""
    text = _UNSAFE.sub("", " ".join(str(value).split()))
    return text[:MAX_FIELD].strip()


def platform_label() -> str:
    """Coarse OS and Python label, e.g. ``Linux 6.12 x86_64, Python 3.13.5``."""
    system = platform.system() or sys.platform
    release = (platform.release() or "").split("-")[0]
    return _clean(f"{system} {release} {platform.machine()}, Python {platform.python_version()}")


def report_url(version: str, system: str | None = None) -> str:
    """The new-issue URL with the bug template and version/OS prefilled."""
    params = {
        "template": TEMPLATE,
        "title": "[Bug] ",
        "version": _clean(version) or "unknown",
        "platform": _clean(system if system is not None else platform_label()) or "unknown",
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    return url if len(url) <= MAX_URL else f"{BASE_URL}?{urlencode({'template': TEMPLATE})}"
