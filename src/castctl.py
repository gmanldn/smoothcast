"""Chromecast control via the catt CLI."""
from __future__ import annotations

import ipaddress
import json
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass


def _find_catt() -> str:
    """Locate the catt binary, preferring the running interpreter's own scripts.

    The launcher provisions catt inside the running interpreter's environment
    (``pip install -e .``), so that copy is the version setup verified. Search
    it before PATH, which may hold a conflicting, older ambient install.
    """
    scripts = pathlib.Path(sys.executable).parent
    for name in ("catt", "catt.exe"):
        candidate = scripts / name
        if candidate.is_file():
            return str(candidate)
    # 1. PATH (canonical: installed via `pip install -e .` / `pip install smoothcast`)
    found = shutil.which("catt")
    if found:
        return found
    # 2. pipx / user-local (Unix)
    for candidate in (
        pathlib.Path.home() / ".local" / "bin" / "catt",
        pathlib.Path.home() / ".local" / "share" / "pipx" / "venvs" / "catt" / "bin" / "catt",
    ):
        if candidate.is_file():
            return str(candidate)
    # 3. Windows user-local (Scripts directory)
    for candidate in (
        pathlib.Path.home() / "AppData" / "Local" / "pipx" / "venvs" / "catt" / "Scripts" / "catt.exe",
        pathlib.Path.home() / "AppData" / "Local" / "pipx" / "venvs" / "catt" / "Scripts" / "catt",
    ):
        if candidate.is_file():
            return str(candidate)
    return "catt"  # last resort — will fail with a clear error


CATT = _find_catt()
DEFAULT_DEVICE = "Living Room TV"


class CastError(RuntimeError):
    pass


def validate_manual_target(address: str) -> str:
    """Accept only unicast LAN IPv4 receivers for manual Cast connections.

    This adds a target to the existing Google Cast backend. It is not a
    generic DLNA/AirPlay connection and never tries to probe other protocols.
    """
    value = str(address).strip()
    try:
        ip = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Enter a valid IPv4 address for a Google Cast receiver") from exc
    if (ip.is_loopback or ip.is_multicast or ip.is_unspecified
            or ip.is_link_local or ip.is_reserved or ip.is_global):
        raise ValueError("Enter a private LAN IPv4 address for a Cast receiver")
    return str(ip)


@dataclass(frozen=True)
class Device:
    name: str
    host: str = ""
    port: int = 0
    model: str = ""
    manufacturer: str = ""
    uuid: str = ""


def _run(args: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(CATT), *args], capture_output=True, text=True, timeout=timeout
    )


def scan(timeout: float = 30) -> list[Device]:
    result = _run(["scan", "-j"], timeout=timeout)
    if result.returncode != 0:
        raise CastError((result.stderr or "device scan failed").strip())
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        raise CastError("device scan returned invalid output") from None
    if not isinstance(data, dict):
        raise CastError("device scan returned an unexpected payload")
    devices = []
    for name, item in sorted(data.items()):
        if not isinstance(item, dict):
            continue
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        devices.append(
            Device(
                name=str(name),
                host=str(item.get("host") or ""),
                port=port if 0 <= port <= 65535 else 0,
                model=str(item.get("model_name") or ""),
                manufacturer=str(item.get("manufacturer") or ""),
                uuid=str(item.get("uuid") or ""),
            )
        )
    return devices


def uniquely_named_device(uuid: str, devices: list[Device]) -> Device | None:
    """Return a discovered physical receiver only with unambiguous identity.

    A friendly name is mutable and may be shared by several TVs. Never
    silently migrate a saved target when its UUID or chosen name collides.
    Devices omitting UUID are deliberately excluded from auto-migration.
    """
    if not isinstance(uuid, str) or not uuid:
        return None
    matches = [d for d in devices if d.uuid == uuid and d.name]
    if len(matches) != 1:
        return None
    match = matches[0]
    return match if sum(d.name == match.name for d in devices) == 1 else None


def info(device: str, timeout: float = 8) -> dict | None:
    """Full device/media status. None when offline or unreachable."""
    try:
        result = _run(["-d", device, "info", "-j"], timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        return None
    if not isinstance(payload, dict) or not payload:
        return None
    return payload


def command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    try:
        result = _run(["-d", device, *args], timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "The device did not respond in time."
    except OSError as exc:
        return False, str(exc)
    message = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return False, message or "The command failed."
    return True, message


def play(device: str) -> tuple[bool, str]:
    return command(device, "play")


def pause(device: str) -> tuple[bool, str]:
    return command(device, "pause")


def play_toggle(device: str) -> tuple[bool, str]:
    return command(device, "play_toggle")


def stop(device: str) -> tuple[bool, str]:
    return command(device, "stop")


def seek(device: str, seconds: float) -> tuple[bool, str]:
    return command(device, "seek", str(max(0, int(seconds))))


def volume(device: str, percent: float) -> tuple[bool, str]:
    level = max(0, min(100, int(round(percent))))
    return command(device, "volume", str(level))


def set_muted(device: str, muted: bool) -> tuple[bool, str]:
    return command(device, "volumemute", "true" if muted else "false")


def subs_on(device: str) -> tuple[bool, str]:
    return command(device, "subs")


def subs_off(device: str) -> tuple[bool, str]:
    return command(device, "subs", "-n")


def player_state(info_dict: dict | None) -> str:
    """Only an explicit receiver IDLE state can prove playback completed.

    Some catt/receiver status payloads contain volume or device identity but
    omit media state. Treating those partial replies as IDLE previously made
    SmoothCast auto-advance, repeat or auto-close a film still playing.
    """
    if not isinstance(info_dict, dict) or not info_dict:
        return "OFFLINE"
    state = str(info_dict.get("player_state") or "").strip().upper()
    return state if state in {"PLAYING", "BUFFERING", "PAUSED", "IDLE"} else "UNKNOWN"


def is_playing(info_dict: dict | None) -> bool:
    return player_state(info_dict) in {"PLAYING", "BUFFERING"}


def is_seekable(info_dict: dict | None) -> bool:
    if not info_dict:
        return False
    return bool(info_dict.get("duration")) and info_dict.get("current_time") is not None


def volume_percent(info_dict: dict | None) -> int | None:
    if not info_dict:
        return None
    raw = info_dict.get("volume_level")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 1.0:
        value *= 100.0
    return int(round(max(0.0, min(100.0, value))))


def volume_muted(info_dict: dict | None) -> bool:
    if not info_dict:
        return False
    return bool(info_dict.get("volume_muted"))


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"