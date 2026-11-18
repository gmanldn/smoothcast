#!/usr/bin/env python3
"""SmoothCast launcher shortcut.

Delegates to ./smoothcast, including its environment bootstrap and dock repair.
Re-launching an active GTK instance raises its window; it does not kill a cast.
"""
import os
from pathlib import Path
import sys

launcher = Path(__file__).resolve().parent / "smoothcast"
if not launcher.is_file() or not os.access(launcher, os.X_OK):
    sys.exit("sc.py: ./smoothcast is missing or not executable")
os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
