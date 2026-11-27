"""Typed, validated views over the persisted config dict (ARCH-05, #693).

The dict in ``cast_widgets.DEFAULTS`` stays the on-disk format. These frozen
groups read it once, coerce every value to a safe type and apply the documented
default, so call sites stop repeating ``cfg.get("key", default)`` with subtly
different defaults and ``is True`` / ``is not False`` conventions.

Pure and GTK-free. Groups so far: update, link/portal, audio, playback. Add groups as call sites
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
    house_pin: bool = False        # require the printed PIN to join
    library_indexer: bool = True   # index the house libraries in the background

    @classmethod
    def from_config(cls, cfg: dict) -> "PortalSettings":
        return cls(port=_port(cfg, "portal_port", 0),
                   hls_port=_port(cfg, "hls_port", 8767) or 8767,
                   screens=_flag(cfg, "portal_screens", True),
                   link_youtube=_flag(cfg, "portal_link_youtube", True),
                   link_magnet=_flag(cfg, "portal_link_magnet", True),
                   house_pin=_flag(cfg, "house_pin_enabled", False),
                   library_indexer=_flag(cfg, "library_indexer", True))


def _number(cfg: dict, key: str, default: float, lo: float, hi: float) -> float:
    value = cfg.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return default
    return min(hi, max(lo, float(value)))


LOUDNESS_MODES = ("off", "programme", "album")


@dataclass(frozen=True)
class AudioSettings:
    gain: float = 6.0              # dB of make-up gain
    loudness: str = "off"          # EBU R128 mode (#139)
    music_autogain: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "AudioSettings":
        mode = cfg.get("audio_loudness", "off")
        return cls(gain=_number(cfg, "audio_gain", 6.0, 0.0, 24.0),
                   loudness=mode if mode in LOUDNESS_MODES else "off",
                   music_autogain=_flag(cfg, "music_autogain", False))


@dataclass(frozen=True)
class PlaybackSettings:
    speed: float = 1.0
    sleep_fade_seconds: int = 30   # 0 = off (#270)
    loop: bool = False
    loop_all: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "PlaybackSettings":
        return cls(speed=_number(cfg, "playback_speed", 1.0, 0.25, 4.0),
                   sleep_fade_seconds=int(_number(cfg, "sleep_fade_seconds", 30, 0, 600)),
                   loop=_flag(cfg, "loop", False), loop_all=_flag(cfg, "loop_all", False))


@dataclass(frozen=True)
class Settings:
    update: UpdateSettings
    portal: PortalSettings
    audio: AudioSettings = AudioSettings()
    playback: PlaybackSettings = PlaybackSettings()

    @classmethod
    def from_config(cls, cfg: object) -> "Settings":
        data = cfg if isinstance(cfg, dict) else {}
        return cls(update=UpdateSettings.from_config(data), portal=PortalSettings.from_config(data),
                   audio=AudioSettings.from_config(data), playback=PlaybackSettings.from_config(data))
