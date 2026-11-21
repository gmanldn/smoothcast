"""Chromecast control via the catt CLI."""
from __future__ import annotations

import ipaddress
import json
import pathlib
import shutil
import math
import subprocess
import sys

import frozen_runtime
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from progress_model import ReceiverInfo


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
# No receiver is assumed on first run: a name the user may not own must never
# be commanded. The empty string means "nothing chosen yet" (issue #239).
DEFAULT_DEVICE = ""
NO_DEVICE_MESSAGE = "No receiver selected. Scan the network and choose one."


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
        catt_command(args), capture_output=True, text=True, timeout=timeout
    )


def catt_command(args: list[str]) -> list[str]:
    return frozen_runtime.catt_command(str(CATT), args)


def _catt_scan(timeout: float = 30) -> list[Device]:
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


def unique_discovered_host(name: str, devices: list[Device]) -> str | None:
    """Resolve a current mDNS host only when the friendly name is unique."""
    matches = [device for device in devices if device.name == name and device.host]
    return matches[0].host if len(matches) == 1 else None


def _catt_info(device: str, timeout: float = 8) -> ReceiverInfo | None:
    """Full device/media status. None when offline or unreachable."""
    if not device.strip():
        return None
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
    return cast(ReceiverInfo, payload)


def _catt_command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    if not device.strip():
        return False, NO_DEVICE_MESSAGE
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


@runtime_checkable
class CastBackend(Protocol):
    """GTK-free receiver boundary used by the existing Cast control helpers.

    This transitional contract captures the operations SmoothCast currently
    exposes through ``castctl``. It deliberately does not yet claim push
    status, connection ownership, or media loading; those belong to the
    complete in-process backend contract tracked by issue #202.
    """

    def scan(self, timeout: float = 30) -> list[Device]: ...

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None: ...

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]: ...


class CattBackend:
    """Compatibility adapter for the current catt command implementation."""

    def scan(self, timeout: float = 30) -> list[Device]:
        return _catt_scan(timeout)

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None:
        return _catt_info(device, timeout)

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
        return _catt_command(device, *args, timeout=timeout)


_backend: CastBackend = CattBackend()


def scan(timeout: float = 30) -> list[Device]:
    """Discover receivers using the active Cast backend."""
    return _backend.scan(timeout)


def info(device: str, timeout: float = 8) -> ReceiverInfo | None:
    """Return receiver status using the active Cast backend."""
    return _backend.info(device, timeout)


def command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    """Run a receiver command using the active Cast backend."""
    return _backend.command(device, *args, timeout=timeout)


def play(device: str) -> tuple[bool, str]:
    return command(device, "play")


def pause(device: str) -> tuple[bool, str]:
    return command(device, "pause")


def play_toggle(device: str) -> tuple[bool, str]:
    return command(device, "play_toggle")


def stop(device: str) -> tuple[bool, str]:
    return command(device, "stop")


def seek_seconds(seconds: float) -> int:
    """Whole seconds catt accepts (it parses with int()): nearest, half up, >= 0.

    Truncating made a seek to 59.9 s land on 59 s; non-finite input maps to 0.
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(value):
        return 0
    return max(0, math.floor(value + 0.5))


def seek(device: str, seconds: float) -> tuple[bool, str]:
    return command(device, "seek", str(seek_seconds(seconds)))


def volume(device: str, percent: float) -> tuple[bool, str]:
    level = max(0, min(100, int(round(percent))))
    return command(device, "volume", str(level))


def set_muted(device: str, muted: bool) -> tuple[bool, str]:
    return command(device, "volumemute", "true" if muted else "false")


def subs_on(device: str) -> tuple[bool, str]:
    return command(device, "subs")


def subs_off(device: str) -> tuple[bool, str]:
    return command(device, "subs", "-n")


def player_state(info_dict: ReceiverInfo | None) -> str:
    """Only an explicit receiver IDLE state can prove playback completed.

    Some catt/receiver status payloads contain volume or device identity but
    omit media state. Treating those partial replies as IDLE previously made
    SmoothCast auto-advance, repeat or auto-close a film still playing.
    """
    if not isinstance(info_dict, dict) or not info_dict:
        return "OFFLINE"
    state = str(info_dict.get("player_state") or "").strip().upper()
    return state if state in {"PLAYING", "BUFFERING", "PAUSED", "IDLE"} else "UNKNOWN"


def is_playing(info_dict: ReceiverInfo | None) -> bool:
    return player_state(info_dict) in {"PLAYING", "BUFFERING"}


def is_seekable(info_dict: ReceiverInfo | None) -> bool:
    if not info_dict:
        return False
    return bool(info_dict.get("duration")) and info_dict.get("current_time") is not None


def volume_percent(info_dict: ReceiverInfo | None) -> int | None:
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


def volume_muted(info_dict: ReceiverInfo | None) -> bool:
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
