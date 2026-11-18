#!/usr/bin/env python3
"""Cross-platform SmoothCast launcher.

The installed Windows environment is started by setup/launch.py; on Unix,
the executable ./smoothcast performs first-run dependency checks.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

if os.name == "nt":
    raise SystemExit(subprocess.call(
        [sys.executable, str(ROOT / "setup" / "launch.py"), *sys.argv[1:]],
        cwd=ROOT,
    ))

launcher = ROOT / "smoothcast"
if not launcher.is_file():
    sys.exit("sc.py: SmoothCast Unix launcher is missing")
os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
