"""Google Cast control boundary with catt and PyChromecast adapters."""
from __future__ import annotations

import ipaddress
import json
import pathlib
import shutil
import math
import os
import subprocess
import sys

import frozen_runtime
from dataclasses import dataclass
from typing import Callable, Protocol, cast, runtime_checkable

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
COMMAND_TIMEOUT_MESSAGE = "The device did not respond in time."


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
        return False, COMMAND_TIMEOUT_MESSAGE
    except OSError as exc:
        return False, str(exc)
    message = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return False, message or "The command failed."
    return True, message


@runtime_checkable
class CastBackend(Protocol):
    """GTK-free receiver boundary used by the existing Cast control helpers.

    This boundary captures operations SmoothCast exposes through ``castctl``.
    Push status is opt-in; connection ownership and media loading remain outside
    this transitional contract.
    """

    supports_push_status: bool

    def scan(self, timeout: float = 30) -> list[Device]: ...

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None: ...

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]: ...

    def subscribe(
        self, device: str, listener: Callable[[ReceiverInfo], None]
    ) -> Callable[[], None] | None: ...

    def close(self) -> None: ...


class CattBackend:
    """Compatibility adapter for the current catt command implementation."""

    supports_push_status = False

    def scan(self, timeout: float = 30) -> list[Device]:
        return _catt_scan(timeout)

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None:
        return _catt_info(device, timeout)

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
        return _catt_command(device, *args, timeout=timeout)

    def subscribe(
        self, _device: str, _listener: Callable[[ReceiverInfo], None]
    ) -> Callable[[], None]:
        """catt has no push status stream; return a safe no-op cancellation."""
        return lambda: None

    def close(self) -> None:
        return None


_backend: CastBackend = CattBackend()
_catt_backend = _backend


def set_backend(backend: CastBackend) -> None:
    """Select a backend instance. Intended for startup configuration and tests."""
    global _backend
    if not isinstance(backend, CastBackend):
        raise TypeError("Cast backend does not implement the required contract")
    previous = _backend
    if previous is not backend:
        previous.close()
    _backend = backend


def use_catt_backend() -> None:
    """Select the compatibility backend for one-release fallback/testing."""
    set_backend(_catt_backend)


def use_pychromecast_backend() -> None:
    """Opt in to the persistent PyChromecast backend while parity is verified."""
    from pychromecast_backend import PyChromecastBackend

    set_backend(PyChromecastBackend())


def configure_backend(name: str | None = None) -> None:
    """Select the backend with SMOOTHCAST_CAST_BACKEND or an explicit name."""
    selected = (name or os.environ.get("SMOOTHCAST_CAST_BACKEND", "catt")).strip().lower()
    if selected == "catt":
        use_catt_backend()
    elif selected == "pychromecast":
        use_pychromecast_backend()
    else:
        raise ValueError("SMOOTHCAST_CAST_BACKEND must be 'catt' or 'pychromecast'")


def supports_push_status() -> bool:
    """Whether the selected backend delivers receiver status changes."""
    return bool(getattr(_backend, "supports_push_status", False))


def subscribe(
    device: str, listener: Callable[[ReceiverInfo], None],
) -> Callable[[], None] | None:
    """Subscribe to status changes without exposing backend implementation details."""
    return _backend.subscribe(device, listener)


class CastStatusWatch:
    """Keep one status subscription aligned with the currently selected Cast target."""

    def __init__(self, listener: Callable[[ReceiverInfo], None]) -> None:
        self._listener = listener
        self._target: str | None = None
        self._unsubscribe: Callable[[], None] | None = None

    def select(self, target: str, enabled: bool) -> bool:
        if self._target == target and (self._unsubscribe is not None) == enabled:
            return enabled
        self.close()
        if enabled:
            unsubscribe = subscribe(target, self._listener)
            if unsubscribe is None:
                return False
            self._target = target
            self._unsubscribe = unsubscribe
        return enabled

    def close(self) -> None:
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        self._target = None
        if unsubscribe is not None:
            unsubscribe()


def watch_status(owner, target: str, eligible: bool, dispatch, listener) -> bool:
    """Keep an owner's selected receiver subscription current and dispatch updates."""
    enabled = eligible and supports_push_status()
    watch = getattr(owner, "_cast_status_watch", None)
    if watch is None and enabled:
        watch = owner._cast_status_watch = CastStatusWatch(
            lambda info: dispatch(listener, info),
        )
    return bool(watch and watch.select(target, enabled))


if os.environ.get("SMOOTHCAST_CAST_BACKEND"):
    configure_backend()


def scan(timeout: float = 30) -> list[Device]:
    """Discover receivers using the active Cast backend."""
    return _backend.scan(timeout)


def info(device: str, timeout: float = 8) -> ReceiverInfo | None:
    """Return receiver status using the active Cast backend."""
    return _backend.info(device, timeout)


def command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    """Run a receiver command using the active Cast backend."""
    return _backend.command(device, *args, timeout=timeout)


def _is_idempotent(args: tuple[str, ...]) -> bool:
    if args in {("play",), ("pause",), ("stop",)}:
        return True
    if len(args) != 2:
        return False
    operation, value = args
    if operation == "seek":
        return value.isdigit()
    if operation == "volume":
        return value.isdigit() and 0 <= int(value) <= 100
    return operation == "volumemute" and value in {"true", "false"}


def idempotent_command(device: str, *args: str) -> tuple[bool, str]:
    """Retry one timed-out absolute transport/volume command exactly once."""
    if not device.strip():
        return False, NO_DEVICE_MESSAGE
    retryable = _is_idempotent(args)
    result = command(device, *args)
    if retryable and result == (False, COMMAND_TIMEOUT_MESSAGE):
        return command(device, *args)
    return result


def play(device: str) -> tuple[bool, str]:
    return idempotent_command(device, "play")


def pause(device: str) -> tuple[bool, str]:
    return idempotent_command(device, "pause")


def play_toggle(device: str) -> tuple[bool, str]:
    return command(device, "play_toggle")


def stop(device: str) -> tuple[bool, str]:
    return idempotent_command(device, "stop")


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
    return idempotent_command(device, "seek", str(seek_seconds(seconds)))


def volume(device: str, percent: float) -> tuple[bool, str]:
    level = max(0, min(100, int(round(percent))))
    return idempotent_command(device, "volume", str(level))


def set_muted(device: str, muted: bool) -> tuple[bool, str]:
    return idempotent_command(device, "volumemute", "true" if muted else "false")


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
