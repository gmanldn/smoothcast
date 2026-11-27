"""One facade that runs the whole mesh inside the app (ticket #405, "M12").

``MeshService`` owns the event loop thread, sockets, beacon, membership,
replication, roles, visibility observer, cache and browser feed, and exposes a
small thread-safe surface: ``start``/``stop``/``status``/``diagnostics``/
``view``/``subscribe``/``set_clients``/``set_screens``. It is **off by default**
(``mesh_enabled`` in config.json) until the Network UI (#403) ships, and with it
off the app behaves exactly as before: no sockets, no threads.

Containment: any failure to start is reported as ``status()['state'] ==
'unavailable'`` and never raises into the caller; exceptions inside mesh
callbacks are counted and the loop keeps running, so playback, the portal and
the GTK thread are never affected. GTK-free.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import random
import secrets
import threading
import time
from typing import Any

import mesh_beacon as mb
import mesh_acquisition_activity
import mesh_acquisition_bridge
import mesh_cache
import mesh_clients
import mesh_heartbeat
import mesh_http
import mesh_membership as mem
import mesh_model as mm
import mesh_policy
import mesh_roles
import mesh_state
import mesh_sync
import mesh_udp
import mesh_visibility as mv
from mesh_rpc import RpcRouter
from mesh_state import MeshView, Subscription

CACHE_SAVE_S = 30.0
MULTICAST_HINT_S = 12.0


def config_path() -> Path:
    import paths  # one place decides where config lives (#701)
    return paths.config_dir() / "config.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Read mesh settings straight from config.json (no side effects, no GTK)."""
    try:
        raw = json.loads((path or config_path()).read_text())
    except (OSError, ValueError, RuntimeError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}

    def acquisition(key: str) -> bool:
        value = raw.get(key, True)
        if raw.get("acquisition_defaults_applied") is not True and value is False:
            return True  # Retire the legacy default-off setting on upgrade.
        return value is True

    return {"enabled": raw.get("mesh_enabled", True) is True,
            "strict": raw.get("mesh_strict") is True,
            "seeds": mb.parse_seeds(raw.get("mesh_seeds", [])
                                    if isinstance(raw.get("mesh_seeds"), list) else []),
            # Only qualified workers on the trusted mesh may execute requests.
            "remote_acquisition": acquisition("mesh_remote_acquisition"),
            "accept_acquisition": acquisition("mesh_accept_acquisition")}


def load_identity(path: Path) -> str:
    """Persistent node id (0600). Regenerated if missing or malformed."""
    try:
        value = json.loads(path.read_text()).get("node_id")
        if isinstance(value, str) and len(value) == 32 and int(value, 16) >= 0:
            return value.lower()
    except (OSError, ValueError, AttributeError):
        pass
    return new_identity(path)


def new_identity(path: Path) -> str:
    node_id = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"node_id": node_id}))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    return node_id


@dataclass
class MeshConfig:
    bind_ip: str
    name: str = "SmoothCast"
    version: str = "0.0.0"
    room_port: int | None = None
    enabled: bool = True
    strict: bool = False
    seeds: tuple[str, ...] = ()
    state_dir: Path = field(default_factory=lambda: config_path().parent)
    cache_path: Path | None = None
    beacon_port: int = mb.DEFAULT_PORT
    multicast: bool = True
    stand_in_peers: tuple[str, ...] = ()
    discovery: Callable[[], Iterable[mv.Discovered]] = lambda: ()
    prober: mv.Prober | None = None
    on_error: Callable[[BaseException], None] | None = None
    link_acquisition_sources: tuple[str, ...] = ()
    link_activity: Callable[[], list] = lambda: []
    # Remote acquisition (#589). Off unless the app supplies a worker and/or an
    # attach hook; ``acquisition_accept`` is the operator's live opt-in.
    acquisition_worker: object | None = None
    acquisition_accept: Callable[[], bool] = lambda: False
    acquisition_attach: Callable[[object], None] | None = None


class MeshService:
    def __init__(self, config: MeshConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self.state = "stopped"          # stopped | running | disabled | unavailable
        self.error = ""
        self.errors = 0
        self.primary_listeners: list = []   # called with each PrimaryChanged (#419)
        self.started_at = 0.0
        self.first_peer_after: float | None = None
        self._screens: list[dict[str, Any]] = []
        self._loop: mesh_udp.MeshLoop | None = None
        self.node_id = ""
        self.cache: mesh_cache.MeshCache | None = None
        self.feed: mesh_clients.MeshFeed | None = None

    # -- lifecycle -----------------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            if self.state == "running":
                return True
            if not self.config.enabled:
                self.state = "disabled"
                return False
            try:
                self._build()
            except Exception as exc:               # contain every startup failure
                self._teardown()
                self.state, self.error = "unavailable", f"{type(exc).__name__}: {exc}"[:200]
                return False
            self.state, self.error = "running", ""
            return True

    def _build(self) -> None:
        cfg = self.config
        identity_path = cfg.state_dir / "mesh_identity.json"
        self.node_id = load_identity(identity_path)
        loop = self._loop = mesh_udp.MeshLoop("smoothcast-mesh", on_error=self._on_error)
        udp = mesh_udp.UdpTransport(loop, cfg.bind_ip, cfg.beacon_port,
                                    multicast=cfg.multicast,
                                    stand_in_peers=list(cfg.stand_in_peers))
        self._udp = udp
        http = self._http = mesh_http.HttpRpc(loop, cfg.bind_ip)
        self._transport = _Composite(udp, http)
        boot_id, epoch = secrets.token_hex(16), int(time.time())
        rng = random.Random(secrets.randbits(64))
        local = mb.LocalState(self.node_id, boot_id, epoch, http.port, rev=1)
        own = mm.NodeRecord(node_id=self.node_id, boot_id=boot_id,
                            name=mm.clean_text(cfg.name, mm.MAX_NAME, fallback="SmoothCast"),
                            version=cfg.version if _valid_version(cfg.version) else "0.0.0",
                            rev=1, boot_epoch=epoch, mesh_port=http.port,
                            room_port=cfg.room_port,
                            capabilities=("room", "screens", mesh_acquisition_activity.HINT,
                                          *((mesh_acquisition_bridge.HINT,)
                                            if cfg.acquisition_worker is not None
                                            or cfg.acquisition_attach is not None else ()),
                                          *((mesh_acquisition_bridge.SEARCH_HINT,)
                                            if cfg.acquisition_worker is not None and cfg.acquisition_accept()
                                            and "youtube" in cfg.link_acquisition_sources else ()), *(
                                "acquire-" + kind + "-local" for kind in ("youtube", "magnet")
                                if kind in cfg.link_acquisition_sources)),
                            addresses=(cfg.bind_ip,))
        self.beacon = mb.Beacon(clock=loop, transport=self._transport, rng=rng, local=local,
                                on_event=self._on_beacon,
                                config=mb.BeaconConfig(seeds=cfg.seeds))
        self.membership = mem.Membership(
            clock=loop, rpc=self._make_rpc(loop), rng=rng, beacon=self.beacon,
            on_event=self._on_membership, on_regenerate=self._regenerate_identity)
        self.mesh_state = mesh_state.MeshState(own, clock=loop)
        self.publisher = mesh_state.ViewPublisher(
            clock=loop, state=self.mesh_state,
            is_alive=lambda n: self.membership.member(n) is not None)
        self.replicator = mesh_sync.Replicator(
            clock=loop, rpc=self.rpc, rng=rng, beacon=self.beacon, membership=self.membership,
            state=self.mesh_state, publisher=self.publisher)
        self.acquisition_activity = mesh_acquisition_activity.AcquisitionActivity(
            clock=loop, rpc=self.rpc, members=self.membership.members,
            record=self.mesh_state.get, own=lambda: self.mesh_state.own,
            version=own.version, local_jobs=cfg.link_activity,
            disabled=lambda node: self.replicator.config.disabled_caps_by_peer.get(node, frozenset()))
        self.acquisition_bridge = None
        if cfg.acquisition_worker is not None or cfg.acquisition_attach is not None:
            loop_thread = lambda: threading.current_thread() is getattr(loop, "_thread", None)  # noqa: E731
            self.acquisition_bridge = mesh_acquisition_bridge.AcquisitionBridge(
                clock=loop, rpc=self.rpc, members=self.membership.members,
                record=self.mesh_state.get, own=lambda: self.mesh_state.own,
                version=own.version, call_soon=loop.call_soon_threadsafe, on_loop=loop_thread,
                disabled=lambda node: self.replicator.config.disabled_caps_by_peer.get(node, frozenset()),
                accept=cfg.acquisition_accept, worker=cfg.acquisition_worker)  # type: ignore[arg-type]
            if cfg.acquisition_attach is not None:
                cfg.acquisition_attach(self.acquisition_bridge)
        self.roles = mesh_roles.PrimaryTracker(
            clock=loop, own_id=self.node_id, own_epoch=epoch,
            members=lambda: [(m.node_id, m.boot_id, m.boot_epoch, m.status == mem.SUSPECT)
                             for m in self.membership.members()],
            on_change=self._on_primary)
        self.observer = mv.LocalObserver(
            clock=loop, rng=rng, source=self._observe_source, publish=self.replicator.update,
            node_edges=lambda: [(m.node_id, loop.monotonic() - m.last_heard)
                                for m in self.membership.members()],
            prober=cfg.prober or self._thread_prober)
        self.cache = mesh_cache.MeshCache(cfg.cache_path or cfg.state_dir / "mesh_cache.sqlite")
        self.cache.open()
        self.feed = mesh_clients.MeshFeed(self.publisher, primary=lambda: self.roles.primary)
        self.heartbeat = mesh_heartbeat.HeartbeatCoordinator(
            sample=self._heartbeat_sample, on_error=self._on_error)
        self.started_at = time.monotonic()
        loop.start()
        loop.call_soon_threadsafe(self._start_components)

    def _thread_prober(self, item: mv.Discovered, done: Callable[[mv.ProbeResult], None]) -> None:
        """Run the blocking TCP connect on a short-lived worker; answer on the loop."""
        loop = self._loop

        def work() -> None:
            result: mv.ProbeResult = (False, None, "no_route")
            try:
                if item.probe is not None:
                    result = mv.connect_probe(*item.probe)
            except Exception:
                pass
            if loop is not None:
                loop.call_soon_threadsafe(lambda: done(result))

        threading.Thread(target=work, name="smoothcast-mesh-probe", daemon=True).start()

    def _probe_round_now(self) -> None:
        """Run a probe round immediately (tests and the Refresh action)."""
        self.observer._probe_round()

    def _make_rpc(self, loop: mesh_udp.MeshLoop) -> RpcRouter:
        policy = mesh_policy.MeshPolicy(
            strict=self.config.strict,
            member_addresses=lambda: [m.address for m in self.membership.members()],
            is_blocked=lambda a: self.membership.is_blocked_address(a))
        self.policy = policy
        self.rpc = RpcRouter(self._transport, authorize=policy.allow, clock=loop)
        return self.rpc

    def _start_components(self) -> None:
        self.beacon.start()
        self.membership.start()
        self.replicator.start()
        self.roles.start()
        self.observer.start()
        self.acquisition_activity.start()
        self.heartbeat.start()
        assert self._loop is not None
        self._loop.call_later(CACHE_SAVE_S, self._save_cache)

    def stop(self, *, graceful: bool = True) -> None:
        with self._lock:
            if self.state in {"stopped", "disabled", "unavailable"}:
                self.state = "stopped" if self.state == "running" else self.state
                return
            loop = self._loop
            if loop is not None:
                done = threading.Event()

                def shutdown() -> None:
                    try:
                        self.heartbeat.stop()
                        self.acquisition_activity.close()
                        if self.acquisition_bridge is not None:
                            self.acquisition_bridge.close()
                        self.observer.close()
                        self.roles.close()
                        self.replicator.close()
                        self.membership.close()
                        if self.feed is not None:
                            self.feed.close()
                        self.publisher.close()
                        self.beacon.close(graceful=graceful)
                    finally:
                        done.set()

                loop.call_soon_threadsafe(shutdown)
                done.wait(3.0)
            self._teardown()
            self.state = "stopped"

    def _teardown(self) -> None:
        for name in ("_http",):
            obj = getattr(self, name, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        udp = getattr(self, "_udp", None)
        if udp is not None:
            try:
                udp.close()
            except Exception:
                pass
        if self.cache is not None:
            try:
                self.cache.close()
            except Exception:
                pass
        beat = getattr(self, "heartbeat", None)
        if beat is not None:
            try:
                beat.stop()
            except Exception:
                pass
        if self._loop is not None:
            self._loop.stop()
            self._loop = None

    def restart(self, bind_ip: str) -> bool:
        """Interface/IP changed: say goodbye on the old one, come back on the new."""
        self.stop(graceful=True)
        self.config.bind_ip = bind_ip
        self.state = "stopped"
        return self.start()

    # -- internal events (loop thread) ----------------------------------------------------
    def _on_error(self, exc: BaseException) -> None:
        self.errors += 1
        self.error = f"{type(exc).__name__}: {exc}"[:200]
        if self.config.on_error is not None:
            try:
                self.config.on_error(exc)
            except Exception:
                pass

    def _on_beacon(self, event: mb.BeaconEvent) -> None:
        if isinstance(event, mb.PeerSeen) and self.first_peer_after is None:
            self.first_peer_after = time.monotonic() - self.started_at
        self.membership.on_beacon_event(event)
        self.replicator.on_beacon_event(event)

    def _on_membership(self, event: mem.MembershipEvent) -> None:
        self.replicator.on_membership_event(event)
        self.publisher.changed()

    def _on_primary(self, change: mesh_roles.PrimaryChanged) -> None:
        for listener in list(getattr(self, "primary_listeners", [])):
            try:
                listener(change)
            except Exception:
                self.errors += 1
        if self.cache is not None and change.new:
            try:
                self.cache.set_last_primary(change.new)
            except Exception:
                self.errors += 1

    def _regenerate_identity(self) -> None:
        """A clone with an earlier start owns our id: take a fresh one and restart."""
        threading.Thread(target=self._regenerate_worker, daemon=True,
                         name="smoothcast-mesh-regen").start()

    def _regenerate_worker(self) -> None:
        ip = self.config.bind_ip
        self.stop(graceful=False)
        try:
            new_identity(self.config.state_dir / "mesh_identity.json")
        except OSError:
            pass
        self.config.bind_ip = ip
        self.start()

    def _save_cache(self) -> None:
        if self.cache is None or self._loop is None or self.state != "running":
            return
        try:
            self.cache.record_view(self.publisher.view)
        except Exception:
            self.errors += 1
        self._loop.call_later(CACHE_SAVE_S, self._save_cache)

    def _observe_source(self) -> list[mv.Discovered]:
        now = self._loop.monotonic() if self._loop is not None else 0.0
        found = list(self.config.discovery())
        for screen in self._screens:
            if isinstance(screen, dict) and str(screen.get("id", "")).isalnum():
                found.append(mv.Discovered(
                    f"screen-{screen['id']}", "screen", str(screen.get("name", "Screen")),
                    now if screen.get("ready") else now - mv.READY_S - 1,
                    model="Browser", busy=screen.get("state") in {"playing", "loading"},
                    formats=("video/mp4", "audio/mpeg") if screen.get("video") else ("audio/mpeg",)))
        return found

    # -- thread-safe inputs ------------------------------------------------------------------
    def set_clients(self, participants: Iterable[dict[str, Any]],
                    screens: Iterable[dict[str, Any]]) -> None:
        """Portal roster + screens changed (any thread)."""
        loop = self._loop
        if self.state != "running" or loop is None:
            return
        people = list(participants)
        shown = list(screens)
        self._screens = shown

        def apply() -> None:
            self.replicator.update(clients=mesh_clients.client_summaries(people, shown))
            self.observer.changed()

        loop.call_soon_threadsafe(apply)

    def discovery_changed(self) -> None:
        loop = self._loop
        if self.state == "running" and loop is not None:
            loop.call_soon_threadsafe(self.observer.changed)

    # -- reads ----------------------------------------------------------------------------------
    @property
    def view(self) -> MeshView | None:
        return self.publisher.view if self.state == "running" else None

    def subscribe(self, **kwargs: Any) -> Subscription | None:
        return self.publisher.subscribe(**kwargs) if self.state == "running" else None

    def warm_start(self) -> mesh_cache.CachedMesh | None:
        """Remembered peers/targets (call on a worker thread)."""
        return self.cache.load() if self.cache is not None and self.state == "running" else None

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state, "error": self.error, "errors": self.errors}
        if self.state != "running":
            return out
        view = self.publisher.view
        out.update(nodes=len(view.nodes), targets=len(view.targets()),
                   primary=self.roles.primary == self.node_id,
                   has_primary=self.roles.primary is not None)
        return out

    def heartbeat_snapshot(self) -> dict[str, Any] | None:
        """Latest dedicated-heartbeat reading, or None when no heartbeat runs."""
        if self.state != "running":
            return None
        beat = getattr(self, "heartbeat", None)
        if beat is None:
            return None
        try:
            return beat.snapshot()
        except Exception:
            return None

    def _heartbeat_sample(self) -> dict[str, Any]:
        """Read-only observation fed to the heartbeat thread (never mutates the mesh)."""
        view = self.publisher.view
        primary_id = self.roles.primary
        names = {record.node_id: record.name for record in view.nodes}
        observations = view.targets()
        nodes = len(view.nodes)
        targets = len(observations)
        ready = sum(1 for _node, target in observations if target.state == "ready")
        clients = sum(len(record.clients) for record in view.nodes)
        return {"mesh_state": self.state, "primary_id": primary_id,
                "primary_name": names.get(primary_id) if primary_id else None,
                "primary_self": primary_id == self.node_id,
                "nodes": nodes, "targets": targets, "targets_ready": ready,
                "clients": clients, "generation": view.generation,
                "activities": _heartbeat_activities(primary_id, names, nodes, targets,
                                                    ready, clients)}

    def diagnostics(self) -> dict[str, Any]:
        """Redacted health: counts and flags only, no names, addresses or ids."""
        out = self.status()
        if self.state != "running":
            return out
        uptime = time.monotonic() - self.started_at
        peers = len(self.membership.members())
        out.update(
            peers=peers, uptime_s=int(uptime),
            join_latency_s=None if self.first_peer_after is None else round(
                self.first_peer_after, 2),
            multicast_hint=("Multicast may be blocked on this network; add a host by address."
                            if peers == 0 and not self.config.seeds
                            and uptime > MULTICAST_HINT_S else ""),
            beacon=_public(self.beacon.stats),
            membership=_public(self.membership.stats),
            replication=_public(self.replicator.stats),
            rpc={"errors": self.rpc.errors, "denied": self.rpc.denied,
                 "rate_limited": self.rpc.rate_limited},
            bytes={"sent": self._udp.sent_bytes, "received": self._udp.recv_bytes},
            cache=self.cache.counts() if self.cache is not None else {},
            threads=sorted(t.name for t in threading.enumerate()
                           if t.name.startswith("smoothcast-mesh")))
        return out


def _public(stats: Any) -> dict[str, int]:
    return {k: v for k, v in vars(stats).items() if isinstance(v, int)}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _heartbeat_activities(primary_id: str | None, names: dict[str, str], nodes: int,
                          targets: int, ready: int, clients: int) -> list[str]:
    """Short, human-readable lines describing what the mesh is doing right now."""
    out: list[str] = []
    if primary_id is None:
        out.append("Waiting for the first node to come up")
    else:
        who = names.get(primary_id)
        out.append(f"{who} coordinates the mesh" if who else "A node coordinates the mesh")
    out.append(_plural(nodes, "node") + " online")
    if targets:
        out.append(f"{ready} of {_plural(targets, 'receiver')} ready")
    if clients:
        out.append(_plural(clients, "connected client"))
    return out


def _valid_version(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(p.isdigit() and len(p) <= 4 for p in parts)


class _Composite:
    """Transport port: datagrams over UDP, requests over HTTP, one lifecycle."""

    def __init__(self, udp: mesh_udp.UdpTransport, http: mesh_http.HttpRpc) -> None:
        self._udp, self._http = udp, http

    @property
    def address(self) -> str:
        return self._udp.address

    def set_datagram_handler(self, handler: Any) -> None:
        self._udp.set_datagram_handler(handler)

    def set_request_handler(self, handler: Any) -> None:
        self._http.set_handler(handler)

    def send_multicast(self, payload: bytes) -> None:
        self._udp.send_multicast(payload)

    def send_unicast(self, address: str, payload: bytes) -> None:
        self._udp.send_unicast(address, payload)

    def request(self, address: str, payload: bytes, callback: Any, timeout: float = 3.0) -> None:
        self._http.request(address, payload, callback, timeout)

    def close(self) -> None:
        self._udp.close()
        self._http.close()
