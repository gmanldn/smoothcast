"""Pytest setup: portable unit tests must never open the user's GTK desktop.

Set the guard at collection time so even subprocesses spawned by tests inherit
it. An intentional GTK smoke test is a separate, opt-in Xvfb run *outside*
pytest: python3 scripts/test_gui_isolated.py.
"""
from __future__ import annotations

import os

os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"
