"""Request/response channel between full nodes over plain HTTP on the LAN (#405).

Implements the ``request`` half of ``mesh_ports.Transport`` for production:
a tiny stdlib HTTP server bound to the private interface (``POST /mesh/v1/rpc``)
and a small thread pool for outgoing calls, so the mesh loop never blocks on a
socket. Incoming payloads are handed to the mesh loop thread and answered from
there, keeping every mesh callback serial. Only private-LAN sources are served;
bodies are capped; concurrency is capped. Pinned-certificate HTTPS for users who
want it is the optional ``mesh_transport`` path (#358). GTK-free.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import mesh_model
from mesh_rpc import MAX_RPC_BYTES
from mesh_udp import MeshLoop

PATH = "/mesh/v1/rpc"
SERVE_TIMEOUT_S = 3.0
MAX_CONCURRENT = 16
CLIENT_WORKERS = 4


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


class HttpRpc:
    def __init__(self, loop: MeshLoop, bind_ip: str, port: int = 0) -> None:
        if not mesh_model.is_lan_address(bind_ip):
            raise ValueError("bind_ip must be a private LAN IPv4 address")
        self._loop = loop
        self._handler: Callable[[str, bytes], bytes | None] | None = None
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self._closed = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 5
            server_version = "SmoothCastMesh"
            sys_version = ""

            def log_message(self, *_a: object) -> None:
                return

            def _reply(self, status: int, body: bytes = b"") -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if body:
                    self.wfile.write(body)
                self.close_connection = True

            def do_POST(self) -> None:  # noqa: N802
                source = self.client_address[0]
                if self.path != PATH or not mesh_model.is_lan_address(source):
                    return self._reply(403)
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    return self._reply(400)
                if not 0 <= length <= MAX_RPC_BYTES:
                    return self._reply(413)
                if not outer._slots.acquire(blocking=False):
                    return self._reply(503)
                try:
                    payload = self.rfile.read(length)
                    reply = outer._call(source, payload)
                finally:
                    outer._slots.release()
                if reply is None:
                    return self._reply(204)
                self._reply(200, reply)

            do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = (  # noqa: N815
                lambda self: self._reply(405))

        self._server = _Server((bind_ip, port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.1},
                                        name="smoothcast-mesh-http", daemon=True)
        self._thread.start()
        self._pool = ThreadPoolExecutor(max_workers=CLIENT_WORKERS,
                                        thread_name_prefix="smoothcast-mesh-rpc")

    # -- server side ---------------------------------------------------------
    def set_handler(self, handler: Callable[[str, bytes], bytes | None] | None) -> None:
        self._handler = handler

    def _call(self, source: str, payload: bytes) -> bytes | None:
        done = threading.Event()
        box: list[bytes | None] = []

        def run() -> None:
            try:
                handler = self._handler
                box.append(handler(source, payload) if handler is not None else None)
            except Exception:
                box.append(None)
            finally:
                done.set()

        self._loop.call_soon_threadsafe(run)
        if not done.wait(SERVE_TIMEOUT_S):
            return None
        return box[0] if box else None

    # -- client side ------------------------------------------------------------
    def request(self, address: str, payload: bytes,
                callback: Callable[[bytes | None, str | None], None],
                timeout: float = 3.0) -> None:
        host, _, port = address.partition(":")
        if self._closed or not port.isdigit() or not mesh_model.is_lan_address(host):
            self._loop.call_soon_threadsafe(lambda: callback(None, "unreachable"))
            return

        def work() -> tuple[bytes | None, str | None]:
            conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
            try:
                conn.request("POST", PATH, body=payload,
                             headers={"Content-Type": "application/octet-stream"})
                response = conn.getresponse()
                body = response.read(MAX_RPC_BYTES + 1)
                if response.status == 200 and len(body) <= MAX_RPC_BYTES:
                    return body, None
                return None, "refused" if response.status in {204, 403} else "failed"
            except TimeoutError:
                return None, "timeout"
            except OSError:
                return None, "unreachable"
            finally:
                conn.close()

        def deliver(future: object) -> None:
            try:
                reply, error = future.result()          # type: ignore[attr-defined]
            except Exception:
                reply, error = None, "failed"
            self._loop.call_soon_threadsafe(lambda: callback(reply, error))

        try:
            self._pool.submit(work).add_done_callback(deliver)
        except RuntimeError:
            self._loop.call_soon_threadsafe(lambda: callback(None, "closed"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._handler = None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(2)
        self._pool.shutdown(wait=False, cancel_futures=True)
