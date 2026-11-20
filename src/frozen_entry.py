"""PyInstaller entry point. Keep bootloader worker handling before GUI imports."""
from __future__ import annotations

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from cli import main

    raise SystemExit(main())
