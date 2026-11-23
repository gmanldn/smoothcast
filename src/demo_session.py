"""Disposable, no-receiver demo profile preparation (#523).

No GTK import, network discovery, receiver control or media generation here.
The later --demo launcher must start its fake receiver and enforce loopback-
only discovery before using this profile.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator


@dataclass(frozen=True)
class DemoSession:
    root: Path
    config_home: Path
    cache_home: Path
    data_home: Path
    runtime_dir: Path
    media_dir: Path

    def environment(self) -> dict[str, str]:
        """Apply these overrides before importing native or settings modules."""
        return {
            "XDG_CONFIG_HOME": str(self.config_home),
            "XDG_CACHE_HOME": str(self.cache_home),
            "XDG_DATA_HOME": str(self.data_home),
            "XDG_RUNTIME_DIR": str(self.runtime_dir),
        }

    @property
    def config_file(self) -> Path:
        return self.config_home / "cast-control" / "config.json"


@contextmanager
def isolated_demo_profile(parent: Path | None = None) -> Iterator[DemoSession]:
    """Yield a fresh private profile and remove it, including on exceptions.

    Device selection intentionally stays blank; a loopback target is unsafe
    until a fake receiver is bound and the discovery path is isolated.
    """
    with tempfile.TemporaryDirectory(prefix="smoothcast-demo-", dir=parent) as temp:
        root = Path(temp).resolve(strict=True)
        paths = {name: root / name
                 for name in ("config", "cache", "data", "runtime", "media")}
        for directory in paths.values():
            directory.mkdir(mode=0o700)
        session = DemoSession(
            root=root, config_home=paths["config"], cache_home=paths["cache"],
            data_home=paths["data"], runtime_dir=paths["runtime"],
            media_dir=paths["media"],
        )
        config = {
            "schema_version": 1,
            "device": "", "device_uuid": "", "cast_targets": [],
            "device_favourites": [], "device_last_used": {},
            "library_folders": [], "library_indexer": False,
            "keep_streaming": False, "check_release_updates": False,
            "release_check_verify": True,
            "recents": [], "favourites": [], "watch_history": [],
            "positions": {},
        }
        destination = session.config_file
        destination.parent.mkdir(mode=0o700)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as writer:
            json.dump(config, writer, sort_keys=True)
            writer.write("\n")
        yield session
