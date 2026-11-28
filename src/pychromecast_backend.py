"""Persistent Google Cast connections backed by PyChromecast.

This adapter is opt-in while the protocol-level parity suite is being built.
It owns discovery, receiver connections and push-driven media status; callers
remain GTK-free and marshal listener callbacks onto their own UI loop.
"""
from __future__ import annotations

import inspect
import mimetypes
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import errors
from castctl import (
    CastError, Device, NO_DEVICE_MESSAGE, ReceiverInfo, log_backend_failure, validate_manual_target,
)


StatusListener = Callable[[ReceiverInfo], None]


def _fail(code: str) -> tuple[bool, str]:
    """Failure result carrying reviewed catalogue copy; records the code (#521)."""
    errors.record(code)
    return False, errors.CATALOGUE[code].message


def _media_call(method: Callable[..., Any], *args: Any, timeout: float,
                **kwargs: Any) -> Any:
    """Call media APIs across PyChromecast 13 and 14 timeout signatures."""
    if "timeout" in inspect.signature(method).parameters:
        kwargs["timeout"] = timeout
    return method(*args, **kwargs)


class _MediaStatusListener:
    def __init__(self, backend: PyChromecastBackend, identifier: str):
        self.backend = backend
        self.identifier = identifier

    def new_media_status(self, status: Any) -> None:
        with self.backend._lock:
            cast = self.backend._casts.get(self.identifier)
        # Keep the running app id on media-status publishes too (#420).
        cast_status = getattr(cast, "status", None) if cast is not None else None
        self.backend._publish(self.identifier, self.backend._status_dict(status, cast_status))

    def load_media_failed(self, _queue_item_id: int, error_code: int) -> None:
        self.backend._publish(
            self.identifier,
            {"player_state": "IDLE", "idle_reason": "ERROR", "error_code": error_code},
        )


class _ConnectionListener:
    def __init__(self, backend: PyChromecastBackend, identifier: str):
        self.backend = backend
        self.identifier = identifier

    def new_connection_status(self, status: Any) -> None:
        self.backend._connection_changed(self.identifier, status)


class _CastStatusListener:
    def __init__(self, backend: PyChromecastBackend, identifier: str):
        self.backend = backend
        self.identifier = identifier

    def new_cast_status(self, status: Any) -> None:
        with self.backend._lock:
            cast = self.backend._casts.get(self.identifier)
        media_status = cast.media_controller.status if cast is not None else None
        self.backend._publish(
            self.identifier, self.backend._status_dict(media_status, status)
        )


@dataclass
class _ManualConnectAttempt:
    done: bool = False
    device: Device | None = None
    error: str | None = None


class PyChromecastBackend:
    """Manage long-lived PyChromecast connections and map SmoothCast commands."""

    supports_push_status = True

    def __init__(
        self,
        *,
        discover: Callable[..., Any] | None = None,
        connect_from_host: Callable[..., Any] | None = None,
    ) -> None:
        if discover is None or connect_from_host is None:
            try:
                import pychromecast
            except ImportError as exc:
                raise CastError("PyChromecast is not installed in this environment") from exc
            discover = discover or pychromecast.get_chromecasts
            connect_from_host = connect_from_host or pychromecast.get_chromecast_from_host

        self._discover = discover
        self._connect_from_host = connect_from_host
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._browser: Any | None = None
        self._casts: dict[str, Any] = {}
        self._devices: dict[str, Device] = {}
        self._media_listeners: dict[str, _MediaStatusListener] = {}
        self._cast_status_listeners: dict[str, _CastStatusListener] = {}
        self._connection_listeners: dict[str, _ConnectionListener] = {}
        self._status: dict[str, ReceiverInfo] = {}
        self._subscribers: dict[str, set[StatusListener]] = {}
        self._connection_state: dict[str, str] = {}
        self._manual_connects: dict[tuple[str, int], _ManualConnectAttempt] = {}
        self._closed = False

    def scan(self, timeout: float = 30) -> list[Device]:
        """Start one ongoing mDNS browser and return discovered receivers.

        A cold call waits up to ``timeout`` for discovery. Once the persistent
        browser has known receivers, later calls return the current snapshot
        immediately while discovery continues in the background. PyChromecast
        maintains receiver connection threads.
        """
        with self._changed:
            if self._closed:
                raise CastError("Cast backend is closed")
            warm_populated = self._browser is not None and bool(self._devices)
            if self._browser is None:
                try:
                    self._browser = self._discover(
                        blocking=False,
                        callback=self._discovered,
                        tries=None,
                        retry_wait=5,
                        timeout=max(1.0, min(timeout, 15.0)),
                    )
                except Exception as exc:  # noqa: BLE001 - third-party discovery failure is re-raised as a coded CastError
                    raise errors.coded(CastError(f"Google Cast discovery failed: {exc}"), "discovery.failed") from exc

            if timeout > 0 and not warm_populated:
                deadline = time.monotonic() + timeout
                while not self._closed:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._changed.wait(remaining)
            return sorted(self._devices.values(), key=lambda item: item.name.casefold())

    def _discovered(self, cast: Any) -> None:
        try:
            self._register(cast)
        except Exception:  # noqa: BLE001 - a malformed mDNS record must not kill zeroconf's thread
            # A malformed or stale mDNS record must not kill zeroconf's thread.
            return

    def _register(self, cast: Any) -> str:
        cast_info = cast.cast_info
        identifier = str(cast_info.uuid)
        with self._changed:
            if self._closed:
                try:
                    cast.disconnect(timeout=1)
                except Exception:  # noqa: BLE001 - best-effort disconnect
                    pass
                return identifier
            if identifier in self._casts:
                if self._casts[identifier] is not cast:
                    try:
                        cast.disconnect(timeout=1)
                    except Exception:  # noqa: BLE001 - best-effort disconnect
                        pass
                return identifier

            endpoint_device = next(
                (device for device in self._devices.values()
                 if device.host == cast_info.host and device.port == cast_info.port),
                None,
            )
            if endpoint_device is not None:
                try:
                    cast.disconnect(timeout=1)
                except Exception:  # noqa: BLE001 - best-effort duplicate disconnect
                    pass
                return endpoint_device.uuid

            name = cast_info.friendly_name or cast_info.host
            self._casts[identifier] = cast
            self._devices[identifier] = Device(
                name=name,
                host=cast_info.host,
                port=cast_info.port,
                model=cast_info.model_name or "",
                manufacturer=cast_info.manufacturer or "",
                uuid=identifier,
            )
            media_listener = _MediaStatusListener(self, identifier)
            cast_status_listener = _CastStatusListener(self, identifier)
            connection_listener = _ConnectionListener(self, identifier)
            self._media_listeners[identifier] = media_listener
            self._cast_status_listeners[identifier] = cast_status_listener
            self._connection_listeners[identifier] = connection_listener
            cast.media_controller.register_status_listener(media_listener)
            cast.register_status_listener(cast_status_listener)
            cast.register_connection_listener(connection_listener)
            try:
                # Request one initial snapshot; subsequent reads use the cache
                # refreshed by PyChromecast's media and receiver listeners.
                cast.media_controller.update_status()
            except Exception:  # noqa: BLE001 - the initial status request is optional
                pass
            self._changed.notify_all()
        return identifier

    def connect_manual(self, address: str, *, port: int = 8009) -> Device:
        """Connect directly to a user-selected private IPv4 Cast target."""
        host = validate_manual_target(address)
        endpoint = (host, port)
        with self._changed:
            if self._closed:
                raise CastError("Cast backend is closed")
            existing = next((d for d in self._devices.values()
                             if d.host == host and d.port == port), None)
            if existing is not None:
                return existing
            attempt = self._manual_connects.get(endpoint)
            if attempt is None:
                attempt = _ManualConnectAttempt()
                self._manual_connects[endpoint] = attempt
                owner = True
            else:
                owner = False
            if not owner:
                while not attempt.done and not self._closed:
                    self._changed.wait()
                if attempt.error is not None:
                    raise CastError(attempt.error)
                if attempt.device is not None:
                    return attempt.device
                raise CastError("Cast backend is closed")

        identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"smoothcast-cast:{host}:{port}")
        try:
            cast = self._connect_from_host(
                (host, port, identifier, None, host),
                tries=None,
                retry_wait=5,
            )
            registered_identifier = self._register(cast)
        except Exception as exc:  # noqa: BLE001 - third-party connect failure is re-raised as CastError
            failure = CastError(f"Cannot connect to Google Cast receiver {host}:{port}: {exc}")
            with self._changed:
                attempt.error = str(failure)
                attempt.done = True
                if self._manual_connects.get(endpoint) is attempt:
                    self._manual_connects.pop(endpoint, None)
                self._changed.notify_all()
            raise failure from exc

        with self._changed:
            device = self._devices.get(registered_identifier)
            if self._closed or device is None:
                attempt.error = "Cast backend is closed" if self._closed else "Cast receiver was not registered"
            else:
                attempt.device = device
            attempt.done = True
            if self._manual_connects.get(endpoint) is attempt:
                self._manual_connects.pop(endpoint, None)
            self._changed.notify_all()
            if attempt.error is not None or device is None:
                raise CastError(attempt.error or "Cast receiver was not registered")
            return device

    def _resolve(self, target: str, *, allow_connect: bool = True) -> tuple[str | None, str | None]:
        value = target.strip()
        if not value:
            return None, NO_DEVICE_MESSAGE
        with self._lock:
            if self._closed:
                return None, "Cast backend is closed"
            matches = [
                identifier
                for identifier, device in self._devices.items()
                if value in {identifier, device.name, device.host}
            ]
        matches = list(dict.fromkeys(matches))
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "Several Google Cast receivers have that name; select one by address."
        if not allow_connect:
            return None, "Receiver is not connected."
        try:
            manual = self.connect_manual(value)
        except ValueError:
            return None, "Receiver is not connected. Scan the network or enter a private LAN IPv4 address."
        except CastError:
            log_backend_failure("Google Cast receiver connection failed", exc_info=True)
            return None, "Could not connect to the receiver. Check its power and network connection."
        return manual.uuid, None

    def info(self, device: str, timeout: float = 8) -> ReceiverInfo | None:
        identifier, error = self._resolve(device)
        if identifier is None:
            return None
        cached = self._cached_status(identifier)
        if cached is not None:
            return cached or None
        with self._lock:
            # Once connection events are available, never reconstruct state
            # from media-controller objects cached before a disconnect.
            if identifier in self._connection_state or self._closed:
                return None
            cast = self._casts.get(identifier)
        if cast is None:
            return None
        try:
            media_status = cast.media_controller.status
            cast_status = cast.status
            snapshot = self._status_dict(media_status, cast_status)
        except Exception:  # noqa: BLE001 - status read falls back to the cached status
            return self._cached_status(identifier) or None
        self._publish(identifier, snapshot)
        # Publication may reject an observation raced by a disconnect or close.
        # Return only the accepted cache, never the discarded local snapshot.
        return self._cached_status(identifier) or None

    def command(self, device: str, *args: str, timeout: float = 12) -> tuple[bool, str]:
        if not args:
            return False, "No Cast command was provided."
        identifier, error = self._resolve(device)
        if identifier is None:
            return False, error or NO_DEVICE_MESSAGE
        with self._lock:
            if self._closed or self._connection_state.get(identifier, "CONNECTED") != "CONNECTED":
                return _fail("cast.not_connected")
            cast = self._casts.get(identifier)
        if cast is None:
            return _fail("cast.not_connected")

        media = cast.media_controller
        action = args[0].lower()
        try:
            if action == "play":
                _media_call(media.play, timeout=timeout)
            elif action == "pause":
                _media_call(media.pause, timeout=timeout)
            elif action == "play_toggle":
                status = self.info(device, timeout=timeout) or {}
                state = status.get("player_state")
                if state in {"PLAYING", "BUFFERING"}:
                    _media_call(media.pause, timeout=timeout)
                elif state == "PAUSED":
                    _media_call(media.play, timeout=timeout)
                else:
                    return _fail("cast.command_failed")
            elif action == "stop":
                _media_call(media.stop, timeout=timeout)
            elif action == "seek" and len(args) > 1:
                _media_call(media.seek, float(args[1]), timeout=timeout)
            elif action == "volume" and len(args) > 1:
                media_level = max(0.0, min(1.0, float(args[1]) / 100.0))
                cast.set_volume(media_level, timeout=timeout)
            elif action == "volumemute" and len(args) > 1:
                cast.set_volume_muted(args[1].lower() == "true", timeout=timeout)
            elif action == "subs":
                if len(args) > 1 and args[1] == "-n":
                    _media_call(media.disable_subtitle, timeout=timeout)
                else:
                    status = media.status
                    tracks = getattr(status, "subtitle_tracks", {}) or {}
                    track_ids = sorted(int(track_id) for track_id in tracks if str(track_id).isdigit())
                    if not track_ids:
                        return _fail("cast.no_subtitle_track")
                    _media_call(media.enable_subtitle, track_ids[0], timeout=timeout)
            elif action == "cast":
                url = next((arg for arg in reversed(args[1:]) if arg.startswith(("http://", "https://"))), "")
                if not url:
                    return _fail("media.url_invalid")
                parsed = urlsplit(url)
                content_type = mimetypes.guess_type(parsed.path)[0] or ""
                if parsed.path.lower().endswith(".m3u8"):
                    # Keep the HLS playlist MIME stable across OS-specific
                    # mimetypes databases (notably macOS' x-mpegurl alias).
                    content_type = "application/vnd.apple.mpegurl"
                if not content_type:
                    return _fail("media.type_unsupported")
                title = PurePosixPath(unquote(parsed.path)).name or "SmoothCast media"
                media_info = None
                if parsed.path.endswith("-fmp4.m3u8"):
                    # Cast defaults unspecified HLS segment formats to TS.
                    # Declare both tracks so the default receiver parses the
                    # experimental CMAF playlist correctly (#246).
                    media_info = {
                        "hlsSegmentFormat": "fmp4",
                        "hlsVideoSegmentFormat": "fmp4",
                    }
                options: dict[str, Any] = {"title": title, "stream_type": "BUFFERED"}
                if media_info is not None:
                    options["media_info"] = media_info
                _media_call(media.play_media, url, content_type, timeout=timeout, **options)
            else:
                return False, f"Unsupported Google Cast command: {action}"
        except (TypeError, ValueError):
            return _fail("cast.command_invalid")
        except Exception:  # noqa: BLE001 - receiver command failure is logged and reported as cast.command_failed
            log_backend_failure("Google Cast receiver command failed", exc_info=True)
            return _fail("cast.command_failed")
        return True, ""

    def subscribe(
        self, device: str, listener: StatusListener,
    ) -> Callable[[], None] | None:
        # watch_status is called on GTK's main context. A new manual-IP
        # connection must happen in the fallback status worker, never here.
        identifier, _error = self._resolve(device, allow_connect=False)
        if identifier is None:
            return None
        with self._lock:
            if self._closed:
                return None
            subscribers = self._subscribers.setdefault(identifier, set())
            subscribers.add(listener)
            current = self._status.get(identifier)
        if current is not None:
            listener(cast(ReceiverInfo, dict(current)))

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.get(identifier, set()).discard(listener)

        return unsubscribe

    def _status_dict(self, media_status: Any, cast_status: Any | None = None) -> ReceiverInfo:
        if media_status is None and cast_status is None:
            return {"player_state": "UNKNOWN"}
        status: ReceiverInfo = {}
        if media_status is not None:
            for field in (
                "player_state", "current_time", "duration", "content_id",
                "idle_reason", "media_session_id",
            ):
                value = getattr(media_status, field, None)
                if value is not None:
                    status[field] = value
            metadata = getattr(media_status, "media_metadata", {}) or {}
            title = metadata.get("title") if isinstance(metadata, dict) else None
            if title:
                status["title"] = str(title)
            status["volume_level"] = getattr(media_status, "volume_level", 1.0)
            status["volume_muted"] = bool(getattr(media_status, "volume_muted", False))
        elif cast_status is not None:
            # Receiver app status alone cannot distinguish an idle receiver
            # from an active media app whose media snapshot has not arrived.
            status["player_state"] = "UNKNOWN"
        if cast_status is not None:
            # Receiver-level facts let callers prove the TV is on its backdrop
            # before showing anything unprompted (#420); absent means unknown.
            if hasattr(cast_status, "app_id"):
                status["app_id"] = cast_status.app_id
            stand_by = getattr(cast_status, "is_stand_by", None)
            if isinstance(stand_by, bool):
                status["is_stand_by"] = stand_by
            active_input = getattr(cast_status, "is_active_input", None)
            if isinstance(active_input, bool):
                status["is_active_input"] = active_input
            level = getattr(cast_status, "volume_level", None)
            muted = getattr(cast_status, "volume_muted", None)
            if level is not None:
                status["volume_level"] = level
            if muted is not None:
                status["volume_muted"] = bool(muted)
            # Real CastStatus always has app_id (None = no app). A status without
            # the attribute stays "unknown" so idle-slate checks fail closed (#420).
            if hasattr(cast_status, "app_id"):
                app_id = cast_status.app_id
                status["app_id"] = app_id if isinstance(app_id, str) else ""
            # A TV in standby or on another input must not be woken or switched.
            stand_by = getattr(cast_status, "is_stand_by", None)
            if isinstance(stand_by, bool):
                status["is_stand_by"] = stand_by
            active_input = getattr(cast_status, "is_active_input", None)
            if isinstance(active_input, bool):
                status["is_active_input"] = active_input
        return status

    def _publish(self, identifier: str, status: ReceiverInfo) -> None:
        with self._lock:
            if self._closed or (status and self._connection_state.get(
                    identifier, "CONNECTED") != "CONNECTED"):
                return
            self._status[identifier] = cast(ReceiverInfo, dict(status))
            listeners = tuple(self._subscribers.get(identifier, ()))
        for listener in listeners:
            try:
                listener(cast(ReceiverInfo, dict(status)))
            except Exception:  # noqa: BLE001 - one bad listener must not stop the others
                continue

    def _cached_status(self, identifier: str) -> ReceiverInfo | None:
        with self._lock:
            status = self._status.get(identifier)
            return cast(ReceiverInfo, dict(status)) if status is not None else None

    def _connection_changed(self, identifier: str, status: Any) -> None:
        value = str(getattr(status, "status", status)).upper()
        with self._lock:
            if self._closed:
                return
            previously = self._connection_state.get(identifier)
            self._connection_state[identifier] = value
            if value != "CONNECTED":
                # Empty status is explicit unavailability, not IDLE or proof
                # of completion. Discard all previously cached media evidence.
                self._status[identifier] = {}
        if value != "CONNECTED":
            self._publish(identifier, {})
        elif previously != "CONNECTED":
            # The receiver came back online. PyChromecast only emits media-status
            # events on change, so a receiver that reconnects while still playing
            # the same content fires no new event and would otherwise appear to
            # stop reporting playback. Re-observe the current status so the device
            # keeps reporting playback instead of going silent.
            self._refresh_status(identifier)

    def _refresh_status(self, identifier: str) -> None:
        """Request fresh receiver and media status after a reconnect."""
        with self._lock:
            if self._closed or identifier not in self._casts:
                return
            cast = self._casts.get(identifier)
        if cast is None:
            return
        # Never republish controller objects cached before the disconnect:
        # they may describe media that is no longer playing. The fresh replies
        # arrive through the registered status listeners.
        for request in (
            lambda: cast.socket_client.receiver_controller.update_status(),
            lambda: cast.media_controller.update_status(),
        ):
            try:
                request()
            except Exception:  # noqa: BLE001 - a refresh request is best-effort
                continue

    def close(self) -> None:
        with self._changed:
            if self._closed:
                return
            self._closed = True
            self._status.clear()
            self._subscribers.clear()
            browser = self._browser
            casts = tuple(self._casts.values())
            self._browser = None
            self._changed.notify_all()
        for chromecast in casts:
            try:
                chromecast.disconnect(timeout=2)
            except Exception:  # noqa: BLE001 - best-effort disconnect on close
                continue
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:  # noqa: BLE001 - best-effort stop on close
                pass
