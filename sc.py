#!/usr/bin/env python3
"""Cross-platform SmoothCast launcher shortcut.

On Unix, delegate to ./smoothcast (automatic first-run setup); on Windows,
launch the isolated runtime installed by setup/winsetup.bat.
"""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parent
if os.name == "nt":
    raise SystemExit(subprocess.call(
        [sys.executable, str(root / "setup" / "launch.py"), *sys.argv[1:]],
        cwd=root,
    ))

launcher = root / "smoothcast"
if not launcher.is_file():
    sys.exit("sc.py: SmoothCast launcher is missing")
os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
