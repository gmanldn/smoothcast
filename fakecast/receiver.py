"""Small loopback CASTV2 receiver used for protocol integration tests.

This is a deterministic development fake, not an implementation of Google's
receiver. It intentionally supports only connection, heartbeat, receiver
status, and a basic media session. Test credentials are self-signed and must
never be used outside local test traffic.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import ssl
import struct
import threading
from typing import Any

try:
    # PyChromecast 14 exposes the generated message type from socket_client.
    from pychromecast.socket_client import CastMessage
except ImportError:  # PyChromecast 13 keeps the same type in its proto module.
    from pychromecast.cast_channel_pb2 import CastMessage


NS_CONNECTION = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA = "urn:x-cast:com.google.cast.media"
DEFAULT_MEDIA_RECEIVER = "CC1AD845"
MAX_FRAME_SIZE = 1024 * 1024


class FakeCastReceiver:
    """Serve a minimal TLS CASTV2 receiver on loopback only."""

    def __init__(
        self, host: str = "127.0.0.1", port: int = 0, *, profile: str = "generic",
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("FakeCastReceiver may bind only to loopback")
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if profile != "generic":
            raise ValueError("only the generic profile is currently available")
        self.host = host
        self.port = port
        self.profile = profile
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._client_threads: set[threading.Thread] = set()
        self._clients: set[ssl.SSLSocket] = set()
        self._tls_context: ssl.SSLContext | None = None
        self._app_id: str | None = None
        self._media_session_id = 1
        self._media_state = "IDLE"
        self._current_time = 0.0
        self._volume = 0.5
        self._muted = False

    def start(self) -> FakeCastReceiver:
        if self._listener is not None:
            return self
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        root = Path(__file__).resolve().parent
        context.load_cert_chain(root / "test_cert.pem", root / "test_key.pem")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(4)
        listener.settimeout(0.2)
        self.port = int(listener.getsockname()[1])
        self._tls_context = context
        self._listener = listener
        self._stopped.clear()
        self._accept_thread = threading.Thread(
            target=self._accept, name="fakecast-accept", daemon=True,
        )
        self._accept_thread.start()
        return self

    def stop(self) -> None:
        self._stopped.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1)
            self._accept_thread = None
        with self._lock:
            threads = list(self._client_threads)
        for thread in threads:
            thread.join(timeout=1)
        with self._lock:
            self._client_threads.clear()
            self._clients.clear()

    def __enter__(self) -> FakeCastReceiver:
        return self.start()

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.stop()

    def _accept(self) -> None:
        listener = self._listener
        while listener is not None and not self._stopped.is_set():
            try:
                raw, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=self._serve, args=(raw,), name="fakecast-client", daemon=True,
            )
            with self._lock:
                self._client_threads.add(thread)
            thread.start()

    def _serve(self, raw: socket.socket) -> None:
        client: ssl.SSLSocket | None = None
        try:
            context = self._tls_context
            if context is None:
                return
            client = context.wrap_socket(raw, server_side=True)
            client.settimeout(0.2)
            with self._lock:
                self._clients.add(client)
            buffer = bytearray()
            while not self._stopped.is_set():
                try:
                    chunk = client.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer.extend(chunk)
                while len(buffer) >= 4:
                    size = struct.unpack(">I", buffer[:4])[0]
                    if size > MAX_FRAME_SIZE:
                        return
                    if len(buffer) < size + 4:
                        break
                    frame = bytes(buffer[4:size + 4])
                    del buffer[:size + 4]
                    message = CastMessage()
                    message.ParseFromString(frame)
                    data = json.loads(message.payload_utf8 or "{}")
                    self._handle(client, message, data)
        except (OSError, ssl.SSLError, ValueError):
            return
        finally:
            if client is not None:
                with self._lock:
                    self._clients.discard(client)
                try:
                    client.close()
                except OSError:
                    pass
            else:
                raw.close()
            with self._lock:
                self._client_threads.discard(threading.current_thread())

    def _handle(
        self,
        client: ssl.SSLSocket,
        message: CastMessage,
        data: dict[str, Any],
    ) -> None:
        namespace = message.namespace
        message_type = str(data.get("type", ""))
        with self._lock:
            self.calls.append((namespace, dict(data)))
        if namespace == NS_HEARTBEAT:
            if message_type == "PING":
                self._send(client, message, namespace, {"type": "PONG"})
            return
        if namespace == NS_CONNECTION:
            return
        if namespace == NS_RECEIVER:
            self._receiver_command(client, message, data)
        elif namespace == NS_MEDIA:
            self._media_command(client, message, data)

    def _receiver_command(
        self,
        client: ssl.SSLSocket,
        request: CastMessage,
        data: dict[str, Any],
    ) -> None:
        message_type = data.get("type")
        if message_type == "LAUNCH":
            with self._lock:
                self._app_id = str(data.get("appId") or DEFAULT_MEDIA_RECEIVER)
            self._send_receiver_status(client, request)
        elif message_type == "STOP":
            with self._lock:
                self._app_id = None
                self._media_state = "IDLE"
            self._send_receiver_status(client, request)
        elif message_type == "SET_VOLUME":
            with self._lock:
                volume = data.get("volume", {})
                if isinstance(volume, dict):
                    self._volume = float(volume.get("level", self._volume))
                    self._muted = bool(volume.get("muted", self._muted))
            self._send_receiver_status(client, request)
        elif message_type == "GET_STATUS":
            self._send_receiver_status(client, request)

    def _send_receiver_status(self, client: ssl.SSLSocket, request: CastMessage) -> None:
        with self._lock:
            app_id = self._app_id
            volume = {"level": self._volume, "muted": self._muted}
        applications = []
        if app_id is not None:
            applications.append({
                "appId": app_id,
                "displayName": "SmoothCast Test Receiver",
                "isIdleScreen": False,
                "namespaces": [{"name": NS_MEDIA}],
                "sessionId": 1,
                "statusText": "Ready to Cast",
                "transportId": "fake-transport-1",
            })
        self._send(client, request, NS_RECEIVER, {
            "type": "RECEIVER_STATUS",
            "status": {
                "applications": applications,
                "isActiveInput": True,
                "isStandBy": False,
                "volume": volume,
            },
        })

    def _media_command(
        self,
        client: ssl.SSLSocket,
        request: CastMessage,
        data: dict[str, Any],
    ) -> None:
        message_type = data.get("type")
        with self._lock:
            if message_type == "LOAD":
                self._media_state = "PLAYING"
                self._current_time = 0.0
            elif message_type == "PLAY":
                self._media_state = "PLAYING"
            elif message_type == "PAUSE":
                self._media_state = "PAUSED"
            elif message_type == "STOP":
                self._media_state = "IDLE"
                self._current_time = 0.0
            elif message_type == "SEEK":
                self._current_time = float(data.get("currentTime", self._current_time))
            status = {
                "currentTime": self._current_time,
                "media": {
                    "contentId": "http://127.0.0.1/fake.mp4",
                    "contentType": "video/mp4",
                    "duration": 120.0,
                    "streamType": "BUFFERED",
                },
                "mediaSessionId": self._media_session_id,
                "playerState": self._media_state,
                "supportedMediaCommands": 15,
                "volume": {"level": self._volume, "muted": self._muted},
            }
        self._send(client, request, NS_MEDIA, {
            "type": "MEDIA_STATUS",
            "status": [status],
        })

    @staticmethod
    def _send(
        client: ssl.SSLSocket,
        request: CastMessage,
        namespace: str,
        data: dict[str, Any],
    ) -> None:
        response = CastMessage()
        response.protocol_version = CastMessage.CASTV2_1_0
        response.source_id = request.destination_id or "receiver-0"
        response.destination_id = request.source_id
        response.payload_type = CastMessage.STRING
        response.namespace = namespace
        if request.HasField("payload_utf8"):
            request_data = json.loads(request.payload_utf8 or "{}")
            if "requestId" in request_data:
                data["requestId"] = request_data["requestId"]
        response.payload_utf8 = json.dumps(data, separators=(",", ":"))
        frame = response.SerializeToString()
        client.sendall(struct.pack(">I", len(frame)) + frame)
