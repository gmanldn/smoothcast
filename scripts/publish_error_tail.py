#!/usr/bin/env python3
"""Publish a bounded, allowlisted error tail for Git-only agents (#620).

Preview is always offline and prints the exact sanitised snapshot that would be
published; publishing is disabled until an owner explicitly configures a
diagnostics repository and branch:

    python3 scripts/publish_error_tail.py --preview
    SMOOTHCAST_ERRTAIL_REPO=owner/diagnostics \\
        python3 scripts/publish_error_tail.py --publish

Only catalogue-known error codes, their approved static messages, bounded
source module basenames from this repository and a UTC timestamp are emitted;
never raw log text, paths, addresses, media names or credentials.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import error_tail  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(error_tail.main())
