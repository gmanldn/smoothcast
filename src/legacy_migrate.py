"""Lossless, idempotent move of legacy data into a new location (#701).

``migrate(old, new)`` copies every file under ``old`` that does not already
exist under ``new``; it never overwrites, never deletes the source (the old
tree stays as the backup) and leaves a marker so later runs do nothing.
Pure stdlib and GTK-free. Returns the relative names copied.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = ".migrated-from-legacy"


def migrate(old: Path | str, new: Path | str) -> list[str]:
    old, new = Path(old), Path(new)
    if not old.is_dir() or old.resolve() == new.resolve() or (new / MARKER).exists():
        return []
    copied: list[str] = []
    for root, _dirs, files in os.walk(old):
        for name in files:
            src = Path(root) / name
            rel = src.relative_to(old)
            dst = new / rel
            if src.is_symlink() or dst.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(src, dst)
            except OSError:
                return copied  # no marker: the next launch retries the rest
            copied.append(rel.as_posix())
    try:
        (new / MARKER).write_text("\n".join(copied), encoding="utf-8")
    except OSError:
        pass
    return copied
