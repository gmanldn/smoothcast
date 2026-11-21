"""Known per-platform test gaps for the native portable-suite jobs (issue #258).

Every entry is a test that fails on that OS in CI for the stated reason. They are
skipped *there only* (never on Linux), by exact test id so passing tests keep
running. This file is the register: fix the cause, then delete the entry.
tests/test_platform_gaps.py checks that every entry still names a real test and
that Linux never skips anything. A reason starting "PRODUCT BUG" is a defect in
SmoothCast itself, not in the test.
"""
from __future__ import annotations

# platform -> {test id relative to tests/: reason}
GAPS: dict[str, dict[str, str]] = {
    "darwin": {},
    "win32": {},
}
