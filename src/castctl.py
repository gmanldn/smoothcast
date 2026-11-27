"""Google Cast control boundary with catt and PyChromecast adapters."""
from __future__ import annotations

import command_trace

import ipaddress
import json
import pathlib
import shutil
import math
import os
import subprocess
import sys
import threading
import time

import frozen_runtime
from dataclasses import dataclass
from typing import Any, Callable, Protocol, cast, runtime_checkable

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
COMMAND_TIMEOUT_MESSAGE = "The receiver did not respond in time."


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
    # All catt invocations (including the encoder's raw cast subprocess) must
    # use the same receiver route. Keep the public/session identity unchanged.
    if len(args) >= 2 and args[0] == "-d" and isinstance(_backend, CattBackend):
        args = [args[0], _backend.receiver_route(args[1]), *args[2:]]
    return frozen_runtime.catt_command(str(CATT), args)


def _passive_cast_scan(timeout: float) -> list[Device]:
    """Discover advertisements without waiting for every receiver to connect."""
    from pychromecast.discovery import discover_chromecasts

    records, browser = discover_chromecasts(timeout=min(max(timeout, 0), 5.0))
    try:
        return sorted([
            Device(str(item.friendly_name or item.host), str(item.host),
                   int(item.port), str(item.model_name or ""),
                   str(item.manufacturer or ""), str(item.uuid or ""))
            for item in records
        ], key=lambda device: (device.name.casefold(), device.uuid))
    finally:
        browser.stop_discovery()


def _receiver_identity_at(host: str) -> str | None:
    """Bounded, read-only identity check; an address alone is not ownership."""
    from pychromecast.dial import get_device_info

    info = get_device_info(host, timeout=2.0)
    return str(info.uuid) if info is not None and info.uuid else None


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


_info_failures: dict[str, str] = {}
# Passive scan (3 s) + identity check (2 s) must fit before an inline retry.
REDISCOVERY_BUDGET = 5.0


def last_info_failure(device: str) -> str:
    """Why the latest status read for ``device`` returned nothing ('' if it worked)."""
    return _info_failures.get(device, "")


def _info_failed(device: str, reason: str) -> None:
    # Log only when the reason changes so a 40 s poll cannot flood errors.log.
    if _info_failures.get(device) != reason:
        log_backend_failure(f"Receiver status unavailable for {device!r}: {reason}")
    _info_failures[device] = reason


def _catt_info(device: str, timeout: float = 8) -> ReceiverInfo | None:
    """Full device/media status. None when offline or unreachable."""
    if not device.strip():
        return None
    try:
        result = _run(["-d", device, "info", "-j"], timeout=timeout)
    except subprocess.TimeoutExpired:
        _info_failed(device, f"status helper timed out after {timeout:g}s")
        return None
    except OSError as exc:
        _info_failed(device, f"status helper could not start: {exc}")
        return None
    if result.returncode != 0:
        tail = " ".join((result.stderr or result.stdout or "").split())[-160:]
        _info_failed(device, f"status helper exited {result.returncode}: {tail}")
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        _info_failed(device, "status helper returned unreadable output")
        return None
    if not isinstance(payload, dict) or not payload:
        _info_failed(device, "status helper returned no data")
        return None
    _info_failures.pop(device, None)
    return cast(ReceiverInfo, payload)


def log_backend_failure(message: str, *, exc_info: bool = False) -> None:
    # Keep diagnostic failure independent of the receiver result.
    try:
        import error_log

        error_log.log(message, exc_info=exc_info)
    except OSError:
        pass


def _record_code(code: str, context: object) -> None:
    """Tag catt failures with the same catalogue codes as the PyChromecast backend (#207)."""
    import errors

    errors.record(code, context)


def _catt_command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    if not device.strip():
        return False, NO_DEVICE_MESSAGE
    try:
        result = _run(["-d", device, *args], timeout=timeout)
    except subprocess.TimeoutExpired:
        _record_code("cast.receiver_offline", {"command": args[:1], "timeout": timeout})
        return False, COMMAND_TIMEOUT_MESSAGE
    except OSError:
        log_backend_failure("Could not start the Cast command helper", exc_info=True)
        _record_code("cast.command_failed", {"command": args[:1], "helper": "unavailable"})
        return False, "Could not start the Cast helper. Check the SmoothCast installation."
    if result.returncode != 0:
        tail = " ".join((result.stderr or result.stdout or "").split())[-160:]
        log_backend_failure(f"Cast command helper exited with code {result.returncode}: {tail}")
        _record_code("cast.command_failed", {"command": args[:1], "exit": result.returncode})
        return False, "The receiver command failed. Check the receiver connection and try again."
    return True, (result.stdout or result.stderr or "").strip()


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

    def __init__(self) -> None:
        self._advertisements: tuple[Device, ...] = ()
        self._last_refresh: dict[str, float] = {}
        self._mirror = _StatusMirror()
        self._mirror_routes: dict[str, str] = {}
        self._verified_hosts: dict[str, tuple[str, float]] = {}

    def _direct_host(self, device: str) -> str | None:
        """A private address safe for the direct connection, without discovery.

        An IP target is used as-is; a name only through the identity-checked
        route of the latest scan, cached for a minute so polls skip the check.
        """
        host = _private_ipv4(device)
        if host is not None:
            return host
        now = time.monotonic()
        cached = self._verified_hosts.get(device)
        if cached is not None and now - cached[1] < 60.0:
            return cached[0]
        host = _private_ipv4(self.receiver_route(device))
        if host is not None:
            self._verified_hosts[device] = (host, now)
        return host

    def scan(self, timeout: float = 30) -> list[Device]:
        try:
            devices = _passive_cast_scan(timeout)
        except Exception:
            # Older/broken discovery environments retain the compatibility
            # path. Its JSON keys collapse duplicate names, so do not use
            # that result as evidence for an automatic IP route.
            self._advertisements = ()
            return _catt_scan(timeout)
        self._advertisements = tuple(devices)
        return devices

    def receiver_route(self, name: str) -> str:
        """Avoid repeated mDNS lookups only for a uniquely verified receiver."""
        matches = [device for device in self._advertisements if device.name == name]
        if len(matches) != 1:
            return name
        selected = matches[0]
        if not selected.uuid or selected.port != 8009:
            return name
        try:
            host = validate_manual_target(selected.host)
            identity = _receiver_identity_at(host)
        except Exception:
            return name
        if identity and identity.replace("-", "").casefold() == selected.uuid.replace("-", "").casefold():
            return host
        # A DHCP reassignment or unavailable identity check is not permission
        # to send a command to the cached IP.
        return name

    def refreshed_route(self, name: str) -> str:
        """Re-discover (at most every 15 s per receiver), then return a verified route."""
        now = time.monotonic()
        if now - self._last_refresh.get(name, -1e9) < 15.0:
            return name
        self._last_refresh[name] = now
        try:
            self._advertisements = tuple(_passive_cast_scan(3.0))
        except Exception:
            return name
        return self.receiver_route(name)

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None:
        # The whole call, retry included, stays within the caller's budget:
        # pollers such as the 40 s cast confirmation depend on it.
        deadline = time.monotonic() + timeout
        if timeout < 0.5:
            if device.strip():
                _info_failed(device, "status read exhausted its timeout budget")
            return None
        # Once a direct connection proved itself for this receiver, answer from
        # it: its pushed status is current and costs no helper start-up.
        failed_host = None
        host = self._mirror_routes.get(device)
        if host is not None:
            if self._mirror.connected(host):
                failed_host = host
                status = self._mirror.info(host, min(timeout, 2.0))
                if status:
                    _info_failures.pop(device, None)
                    return status
            self._mirror_routes.pop(device, None)
            self._mirror.forget(host)
        # catt's start-up alone can take most of the budget on a loaded host,
        # leaving the fallback below no time to prove the direct route. Try a
        # known safe address first with a bounded slice, then catt (#712).
        remaining = deadline - time.monotonic()
        host = None
        if remaining >= 0.5 and device.strip():
            # Verifying a discovered name may itself take two seconds.
            if remaining >= 2.5 or _private_ipv4(device) is not None:
                host = self._direct_host(device)
        remaining = deadline - time.monotonic()
        if host is not None and host != failed_host and remaining >= 0.5:
            status = self._mirror.info(host, min(remaining, 4.0, max(0.5, timeout / 2)))
            if status:
                _info_failures.pop(device, None)
                self._mirror_routes[device] = host
                return status
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            if device.strip():
                _info_failed(device, "status read exhausted its timeout budget")
            return None
        result = _catt_info(device, remaining)
        if result is not None or not device.strip():
            return result
        # catt's own name lookup can fail where a verified address works.
        route = device
        if deadline - time.monotonic() >= REDISCOVERY_BUDGET:
            route = self.refreshed_route(device)
            remaining = deadline - time.monotonic()
            if route != device and remaining >= 1.0:
                retried = _catt_info(route, remaining)
                if retried is not None:
                    _info_failures.pop(device, None)
                    return retried
        elif time.monotonic() - self._last_refresh.get(device, -1e9) >= 15.0:
            # No room for discovery plus a retry here; learn the route in the
            # background so the next call (via catt_command) can use it.
            threading.Thread(target=self.refreshed_route, args=(device,),
                             name="cast-route-refresh", daemon=True).start()
        return self._mirror_info(device, route, deadline)

    def _mirror_info(self, device: str, route: str, deadline: float) -> ReceiverInfo | None:
        """Read status over a persistent read-only connection when catt fails.

        Spawning catt costs seconds of Python start-up on a loaded host; a kept
        connection answers instantly. Only a private IPv4 address that is the
        target itself or passed the receiver identity check is used.
        """
        host = _private_ipv4(route) or _private_ipv4(device)
        if host is None and deadline - time.monotonic() >= 2.5:
            host = _private_ipv4(self.receiver_route(device))
        remaining = deadline - time.monotonic()
        if host is None or remaining < 0.5:
            return None
        status = self._mirror.info(host, remaining)
        if status:
            _info_failures.pop(device, None)
            self._mirror_routes[device] = host
        return status

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
        return _catt_command(device, *args, timeout=timeout)

    def subscribe(
        self, _device: str, _listener: Callable[[ReceiverInfo], None]
    ) -> Callable[[], None]:
        """catt has no push status stream; return a safe no-op cancellation."""
        return lambda: None

    def close(self) -> None:
        self._advertisements = ()
        self._mirror_routes.clear()
        self._verified_hosts.clear()
        self._mirror.close()


def _private_ipv4(value: str) -> str | None:
    try:
        return validate_manual_target(value)
    except ValueError:
        return None


_CATT_MEDIA_KEYS = (
    "content_type", "stream_type", "media_metadata", "subtitle_tracks",
    "current_subtitle_tracks", "supported_media_commands", "playback_rate",
    "idle_reason", "duration", "media_custom_data",
)


class _StatusMirror:
    """Kept read-only PyChromecast connections, keyed by verified host.

    Never launches apps or sends media commands; catt keeps media ownership.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._casts: dict[str, object] = {}

    def info(self, host: str, timeout: float) -> ReceiverInfo | None:
        deadline = time.monotonic() + timeout
        try:
            import pychromecast
            from pychromecast_backend import PyChromecastBackend

            with self._lock:
                chromecast = self._casts.get(host)
            if chromecast is None:
                chromecast = pychromecast.get_chromecast_from_host(
                    (host, 8009, None, None, None), tries=1,
                    timeout=max(0.5, min(5.0, timeout)), retry_wait=1)
                with self._lock:
                    self._casts[host] = chromecast
            cc = cast(Any, chromecast)
            cc.wait(timeout=max(0.1, deadline - time.monotonic()))
            cast_status = cc.status
            media = cc.media_controller
            app_id = getattr(cast_status, "app_id", None)
            if app_id and getattr(media.status, "media_session_id", None) is None:
                # A freshly joined app reports its media session shortly after.
                try:
                    media.update_status()
                except Exception as exc:
                    log_backend_failure(f"media status refresh failed: {exc}")
                wait_until = min(deadline, time.monotonic() + 1.5)
                while (time.monotonic() < wait_until
                       and getattr(media.status, "media_session_id", None) is None):
                    time.sleep(0.05)
            status = PyChromecastBackend._status_dict(
                cast(Any, None), media.status, cast_status)
            # A kept connection's last report ages; extrapolate like the receiver.
            adjusted = getattr(media.status, "adjusted_current_time", None)
            if isinstance(adjusted, (int, float)) and "current_time" in status:
                status["current_time"] = adjusted
            for key in ("display_name", "status_text"):
                value = getattr(cast_status, key, None)
                if value:
                    status[key] = value  # type: ignore[literal-required]
            # Same media keys as `catt info -j`, so every caller sees one shape.
            for key in _CATT_MEDIA_KEYS:
                value = getattr(media.status, key, None)
                if value is not None and key not in status:
                    status[key] = value  # type: ignore[literal-required]
            return status
        except Exception as exc:
            self._drop(host)
            _info_failed(host, f"direct status connection failed: {type(exc).__name__}")
            return None

    def connected(self, host: str) -> bool:
        """True only while the kept socket is live; stale caches never answer."""
        with self._lock:
            chromecast = self._casts.get(host)
        try:
            client = getattr(chromecast, "socket_client", None)
            return bool(client is not None and client.is_connected)
        except Exception:
            return False

    def forget(self, host: str) -> None:
        self._drop(host)

    def _drop(self, host: str) -> None:
        with self._lock:
            chromecast = self._casts.pop(host, None)
        if chromecast is not None:
            try:
                cast(Any, chromecast).disconnect(timeout=1)
            except Exception as exc:
                log_backend_failure(f"receiver disconnect failed: {exc}")

    def close(self) -> None:
        with self._lock:
            hosts = list(self._casts)
        for host in hosts:
            self._drop(host)


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

    def __init__(self, listener: Callable[[ReceiverInfo], None], dispatch=None) -> None:
        self._listener = listener
        self._dispatch = dispatch
        self._target: str | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._generation = 0

    def select(self, target: str, enabled: bool) -> bool:
        if self._target == target and (self._unsubscribe is not None) == enabled:
            return enabled
        self.close()
        if enabled:
            generation = self._generation
            self._target = target

            def deliver(info):
                # Check on the UI context, not only before scheduling an idle.
                # The selected target may change while a callback is queued.
                if generation == self._generation and self._target == target:
                    self._listener(info)
                return False

            def receive(info):
                if generation != self._generation:
                    return
                if self._dispatch is None:
                    deliver(info)
                else:
                    self._dispatch(deliver, info)

            unsubscribe = subscribe(target, receive)
            if unsubscribe is None:
                self.close()
                return False
            self._unsubscribe = unsubscribe
        return enabled

    def close(self) -> None:
        self._generation += 1
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        self._target = None
        if unsubscribe is not None:
            unsubscribe()


def watch_status(owner, target: str, eligible: bool, dispatch, listener) -> bool:
    """Keep an owner's selected receiver subscription current and dispatch updates."""
    enabled = eligible and supports_push_status()
    watch = getattr(owner, "_cast_status_watch", None)
    if watch is None and enabled:
        watch = owner._cast_status_watch = CastStatusWatch(listener, dispatch)
    return bool(watch and watch.select(target, enabled))


import demo_mode  # noqa: E402

if demo_mode.active():
    # Demo: only the profile's loopback fake receiver; never mDNS or catt (#454).
    demo_mode.install_network_guard()
    set_backend(demo_mode.backend())
elif os.environ.get("SMOOTHCAST_CAST_BACKEND"):
    configure_backend()


def scan(timeout: float = 30) -> list[Device]:
    """Discover receivers using the active Cast backend."""
    return _backend.scan(timeout)


def info(device: str, timeout: float = 8) -> ReceiverInfo | None:
    """Return receiver status using the active Cast backend."""
    result = _backend.info(device, timeout)
    if result is not None:
        command_trace.stage("status_observed")
        if isinstance(result, dict):
            command_trace.observe_receiver(device, player_state(result))
    return result


def command(device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
    """Run a receiver command using the active Cast backend."""
    command_trace.clear_receiver_expectation()
    command_trace.stage("receiver_call")
    try:
        accepted, response = _backend.command(device, *args, timeout=timeout)
    except Exception:
        command_trace.stage("receiver_failed", code=502)
        raise
    command_trace.stage("receiver_ack" if accepted else "receiver_failed",
                        code=None if accepted else 502)
    if accepted and len(args) == 1:
        expected = {"play": "PLAYING", "pause": "PAUSED", "stop": "IDLE"}.get(args[0])
        if expected is not None:
            command_trace.expect_receiver(device, expected)
    return accepted, response


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
    """Human display: m:ss below one hour; h:mm:ss afterwards.

    Only seconds and minutes within an hour are padded. Unknown/non-finite
    positions use --:--; negative source positions clamp to zero.
    DLNA's HH:MM:SS protocol time is deliberately a different formatter.
    """
    if seconds is None or not math.isfinite(seconds):
        return "--:--"
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def fmt_remaining(seconds: float | None) -> str:
    """Display remaining source time with a leading minus sign."""
    formatted = fmt_time(seconds)
    return formatted if formatted == "--:--" else "-" + formatted
