"""Freeze the HLS worker generation so a mid-session checkout change never mixes code.

The GUI, this process's already-imported modules and every subprocess that
re-executes repository code must all be the same generation. On first use we
copy the HLS worker (``server.py``) and its repository-local imports into a
private per-generation directory under the cache root and launch from that
snapshot. A later ``git pull`` therefore cannot change the code an already
running SmoothCast executes; the next launch picks up the new generation.
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
from pathlib import Path

GENERATION_PREFIX = "hls-generation-"


def is_frozen_worker(path: str) -> bool:
    """True for a worker launched from a private generation snapshot."""
    parts = str(path).replace("\\", "/").split("/")
    return (len(parts) >= 2 and parts[-1] == "server.py"
            and parts[-2].startswith(GENERATION_PREFIX))


def _collect_local(module: Path, src_dir: Path, found: dict[str, bytes]) -> None:
    """Gather *module* and every repository-local module it imports, transitively."""
    if module.name in found or not module.is_file():
        return
    try:
        source = module.read_bytes()
        tree = ast.parse(source.decode("utf-8", "replace"))
    except (OSError, SyntaxError, ValueError):
        return
    found[module.name] = source
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for dotted in names:
            _collect_local(src_dir / f"{dotted.split('.')[0]}.py", src_dir, found)


def freeze_worker(script: Path, cache_root: Path) -> Path:
    """Return a stable ``server.py`` path for the generation loaded now.

    Copies the worker and its repository-local imports once into
    ``<cache_root>/hls-generation-<digest>`` atomically. Returns the live
    ``script`` unchanged if the snapshot cannot be written; never raises.
    """
    script = Path(script)
    src_dir = script.parent
    modules: dict[str, bytes] = {}
    _collect_local(script, src_dir, modules)
    if script.name not in modules:
        return script
    digest = hashlib.sha256()
    for name in sorted(modules):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(modules[name])
    target = cache_root / f"{GENERATION_PREFIX}{digest.hexdigest()[:12]}"
    snapshot = target / script.name
    if snapshot.is_file():
        return snapshot
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for name, data in modules.items():
            (staging / name).write_bytes(data)
        try:
            os.replace(staging, target)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            if not snapshot.is_file():
                return script
        return snapshot if snapshot.is_file() else script
    except OSError:
        return script
