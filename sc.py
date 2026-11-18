#!/usr/bin/env python3
"""sc.py — cleanly (re)start SmoothCast from its self-managed venv.

A thin wrapper that delegates to the ``./smoothcast`` launcher, which bootstraps
the venv on first run (Python 3.10+, GTK4/libadwaita, ffmpeg, catt) and then
execs ``src/cast_control.py``. Running this again cleanly restarts the app.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(ROOT, "smoothcast")

if not os.path.isfile(LAUNCHER):
    sys.stderr.write("sc.py: ./smoothcast launcher not found in project root\n")
    sys.exit(1)

os.execv(sys.executable if False else LAUNCHER, [LAUNCHER] + sys.argv[1:])
