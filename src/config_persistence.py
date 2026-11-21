"""GTK-free config persistence wiring shared by every GUI save callback."""
from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Callable

import config_control

_path: Path | None = None
_defaults: dict | None = None
_writer: config_control.DebouncedWriter | None = None
_on_error: Callable[[str], None] | None = None
_lock = threading.Lock()


def configure(path: Path, defaults: dict, on_error: Callable[[str], None]) -> None:
    global _path, _defaults, _on_error
    _path = Path(path)
    _defaults = defaults
    _on_error = on_error


def _config_writer() -> config_control.DebouncedWriter:
    global _writer
    if _path is None:
        raise RuntimeError("config persistence is not configured")
    with _lock:
        if _writer is None:
            _writer = config_control.DebouncedWriter(
                lambda cfg: config_control.save_file(_path, cfg, snapshot_only=True),
                on_error=_on_error or logging.error,
            )
    return _writer


def save_config(cfg: dict) -> None:
    _config_writer().submit(cfg)


def refresh_config(cfg: dict) -> bool:
    if _path is None or _defaults is None:
        return False
    return config_control.refresh_file(_path, cfg, _defaults)


def flush_config() -> bool:
    if _writer is None:
        return True
    ok = _writer.flush()
    if not ok and _on_error is not None:
        _on_error("SmoothCast settings did not finish saving during shutdown")
    return ok
