"""Typed, validated views over the persisted config dict (ARCH-05, #693).

The dict in ``cast_widgets.DEFAULTS`` stays the on-disk format. These frozen
groups read it once, coerce every value to a safe type and apply the documented
default, so call sites stop repeating ``cfg.get("key", default)`` with subtly
different defaults and ``is True`` / ``is not False`` conventions.

Pure and GTK-free. Groups so far: update, link/portal. Add groups as call sites
migrate; never read these keys by literal outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass

UPDATE_CHANNELS = ("develop", "main")


def _flag(cfg: dict, key: str, default: bool) -> bool:
    value = cfg.get(key, default)
    return value if isinstance(value, bool) else default


def _port(cfg: dict, key: str, default: int = 0) -> int:
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 0 <= value <= 65535 else default


@dataclass(frozen=True)
class UpdateSettings:
    channel: str = "develop"
    check_releases: bool = False   # opt-in; legacy auto_update is ignored (#138)
    verify_release: bool = True    # a non-boolean value never weakens verification

    @classmethod
    def from_config(cls, cfg: dict) -> "UpdateSettings":
        channel = cfg.get("update_channel")
        return cls(channel=channel if channel in UPDATE_CHANNELS else "develop",
                   check_releases=cfg.get("check_release_updates") is True,
                   verify_release=cfg.get("release_check_verify") is not False)


@dataclass(frozen=True)
class PortalSettings:
    port: int = 0                  # 0 = choose and persist a random high port (#456)
    hls_port: int = 8767
    screens: bool = True
    link_youtube: bool = True
    link_magnet: bool = True

    @classmethod
    def from_config(cls, cfg: dict) -> "PortalSettings":
        return cls(port=_port(cfg, "portal_port", 0),
                   hls_port=_port(cfg, "hls_port", 8767) or 8767,
                   screens=_flag(cfg, "portal_screens", True),
                   link_youtube=_flag(cfg, "portal_link_youtube", True),
                   link_magnet=_flag(cfg, "portal_link_magnet", True))


@dataclass(frozen=True)
class Settings:
    update: UpdateSettings
    portal: PortalSettings

    @classmethod
    def from_config(cls, cfg: object) -> "Settings":
        data = cfg if isinstance(cfg, dict) else {}
        return cls(update=UpdateSettings.from_config(data), portal=PortalSettings.from_config(data))
