"""MPRIS2 media-player integration for Linux desktops (#266).

Publishes SmoothCast on the session bus as ``org.mpris.MediaPlayer2.smoothcast``
so GNOME/KDE media widgets and media keys (play/pause, next, previous, seek)
control playback without focusing the window.

The module is import-safe under pytest: the Gio/GLib import is lazy, so the
logic and its tests stay GTK- and gi-free. The pure layer maps a controller to
plain Python property values; ``GioBus`` is the only part that touches Gio and
converts those values to ``GLib.Variant`` on the wire. ``WindowAdapter`` maps a
``MainWindow`` onto the controller protocol.
"""
from __future__ import annotations

import hashlib
import state_labels
import pathlib
import platform
from dataclasses import dataclass

BUS_NAME = "org.mpris.MediaPlayer2.smoothcast"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_INTERFACE = "org.mpris.MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DEFAULT_TRACK = "/org/mpris/MediaPlayer2/Track/0"

INTROSPECTION_XML = f"""
<node>
  <interface name="{ROOT_INTERFACE}">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="{PLAYER_INTERFACE}">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
    <method name="SetPosition">
      <arg name="TrackId" type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Shuffle" type="b" access="read"/>
    <property name="Metadata" type="a{{sv}}" access="read"/>
    <property name="Volume" type="d" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""

# Scalar snapshot fields worth a PropertiesChanged signal. Position is
# deliberately excluded: MPRIS says clients poll it, and a cast advances it
# every tick, which would flood the bus.
_SCALAR_PROPERTIES = {
    "playback_status": "PlaybackStatus",
    "volume": "Volume",
    "can_play": "CanPlay",
    "can_pause": "CanPause",
    "can_go_next": "CanGoNext",
    "can_go_previous": "CanGoPrevious",
    "can_seek": "CanSeek",
    "can_control": "CanControl",
}
_METADATA_FIELDS = ("title", "artist", "album", "track_id", "length_us", "art_url")
# D-Bus signatures for the ``a{sv}`` metadata payload.
_METADATA_TYPES = {
    "mpris:trackid": "o", "mpris:length": "x", "xesam:title": "s",
    "xesam:artist": "as", "xesam:album": "s", "mpris:artUrl": "s",
}


@dataclass(frozen=True)
class MprisSnapshot:
    """A frozen view of what the player should report right now."""

    playback_status: str = "Stopped"
    title: str = ""
    artist: str = ""
    album: str = ""
    track_id: str = ""
    length_us: int = 0
    position_us: int = 0
    art_url: str = ""
    volume: float = 1.0
    can_play: bool = False
    can_pause: bool = False
    can_go_next: bool = False
    can_go_previous: bool = False
    can_seek: bool = False
    can_control: bool = False


def _track_id(path: str) -> str:
    """A stable MPRIS track id (a valid object path) for a media file."""
    if not path:
        return DEFAULT_TRACK
    return "/org/mpris/MediaPlayer2/Track/" + hashlib.sha1(
        pathlib.Path(path).as_posix().encode("utf-8")).hexdigest()


def metadata_dict(snapshot: MprisSnapshot) -> dict[str, object]:
    return {
        "mpris:trackid": snapshot.track_id or DEFAULT_TRACK,
        "mpris:length": max(0, int(snapshot.length_us)),
        "xesam:title": snapshot.title,
        "xesam:artist": [snapshot.artist] if snapshot.artist else [],
        "xesam:album": snapshot.album,
        "mpris:artUrl": snapshot.art_url,
    }


def _scalar_value(prop: str, snapshot: MprisSnapshot) -> object:
    if prop == "PlaybackStatus":
        return snapshot.playback_status
    if prop == "Volume":
        return float(snapshot.volume)
    for field, name in _SCALAR_PROPERTIES.items():
        if name == prop:
            return bool(getattr(snapshot, field))
    raise KeyError(prop)


def root_values() -> dict[str, object]:
    return {
        "CanQuit": True,
        "CanRaise": True,
        "HasTrackList": False,
        "Identity": "SmoothCast",
        "DesktopEntry": "local.cast-control",
        "SupportedUriSchemes": [],
        "SupportedMimeTypes": [],
    }


def player_values(snapshot: MprisSnapshot) -> dict[str, object]:
    values: dict[str, object] = {
        "PlaybackStatus": snapshot.playback_status,
        "LoopStatus": "None",
        "Rate": 1.0,
        "Shuffle": False,
        "Metadata": metadata_dict(snapshot),
        "Volume": float(snapshot.volume),
        "Position": max(0, int(snapshot.position_us)),
        "MinimumRate": 1.0,
        "MaximumRate": 1.0,
    }
    for field, name in _SCALAR_PROPERTIES.items():
        values.setdefault(name, _scalar_value(name, snapshot))
    return values


def _metadata_changed(new: MprisSnapshot, old: MprisSnapshot) -> bool:
    return any(getattr(new, field) != getattr(old, field) for field in _METADATA_FIELDS)


def _params_tuple(params) -> tuple:
    if params is None:
        return ()
    unpack = getattr(params, "unpack", None)
    return tuple(unpack()) if callable(unpack) else tuple(params)


class MprisService:
    """Serialize a controller onto MPRIS2 properties, methods and signals."""

    def __init__(self, bus, controller, marshal=None) -> None:
        self._bus = bus
        self._controller = controller
        # MPRIS calls arrive on the D-Bus dispatch thread; commands that touch
        # GTK must run on the main loop. The default is a direct call (tests).
        self._marshal = marshal or (lambda command: command())
        self._last = MprisSnapshot()

    def publish(self) -> None:
        self._bus.publish(self)
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        snapshot = self._controller.snapshot()
        if force:
            self._last = snapshot
            self._bus.emit_properties_changed(PLAYER_INTERFACE, player_values(snapshot))
            return
        changed: dict[str, object] = {}
        for field, prop in _SCALAR_PROPERTIES.items():
            if getattr(snapshot, field) != getattr(self._last, field):
                changed[prop] = _scalar_value(prop, snapshot)
        if _metadata_changed(snapshot, self._last):
            changed["Metadata"] = metadata_dict(snapshot)
        self._last = snapshot
        if changed:
            self._bus.emit_properties_changed(PLAYER_INTERFACE, changed)

    def property_value(self, interface: str, name: str):
        snapshot = self._controller.snapshot()
        if interface == ROOT_INTERFACE:
            return root_values().get(name)
        if interface == PLAYER_INTERFACE:
            return player_values(snapshot).get(name)
        return None

    def invoke(self, interface: str, method: str, params=None) -> None:
        if interface == ROOT_INTERFACE:
            if method == "Raise":
                self._marshal(self._controller.raise_window)
            elif method == "Quit":
                self._marshal(self._controller.quit_app)
            return
        if interface != PLAYER_INTERFACE:
            return
        simple = {
            "Play": self._controller.play,
            "Pause": self._controller.pause,
            "PlayPause": self._controller.play_pause,
            "Stop": self._controller.stop,
            "Next": self._controller.next,
            "Previous": self._controller.previous,
        }
        if method in simple:
            self._marshal(simple[method])
        elif method == "Seek":
            values = _params_tuple(params)
            offset = values[0] if values else 0
            self._marshal(lambda: self._controller.seek(int(offset)))
        elif method == "SetPosition":
            track_id, position = _params_tuple(params)
            self._marshal(lambda: self._controller.set_position(str(track_id), int(position)))
        # OpenUri and unknown methods are accepted and ignored: the player does
        # not stream arbitrary URIs, and a spurious client must not break it.


def _gio():
    """Import Gio/GLib lazily so importing this module never pulls in gi."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib


def _to_variant(GLib, signature: str, value):
    if signature == "a{sv}":
        return GLib.Variant("a{sv}", {
            key: _to_variant(GLib, _METADATA_TYPES[key], item)
            for key, item in dict(value).items()
        })
    if signature == "as":
        return GLib.Variant("as", list(value))
    if signature == "b":
        return GLib.Variant("b", bool(value))
    if signature == "d":
        return GLib.Variant("d", float(value))
    if signature == "x":
        return GLib.Variant("x", int(value))
    if signature == "o":
        return GLib.Variant("o", str(value))
    return GLib.Variant("s", str(value))


class GioBus:
    """The production MPRIS bus: a real ``org.freedesktop.DBus`` connection."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._owner_id: int | None = None
        self._types: dict[tuple[str, str], str] = {}

    def publish(self, service: MprisService) -> None:
        Gio, _GLib = _gio()
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        for interface in node.interfaces:
            for prop in interface.properties:
                self._types[(interface.name, prop.name)] = prop.signature

        def on_call(_conn, _sender, _path, interface, method, params, invocation):
            service.invoke(interface, method, params)
            invocation.return_value(None)

        def on_get(_conn, _sender, _path, interface, prop):
            value = service.property_value(interface, prop)
            signature = self._types.get((interface, prop))
            if value is None or signature is None:
                return None
            return _to_variant(_GLib, signature, value)

        for interface in node.interfaces:
            self._connection.register_object(
                OBJECT_PATH, interface, on_call, on_get, None)
        self._owner_id = Gio.bus_own_name_on_connection(
            self._connection, BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)

    def emit_properties_changed(self, interface: str, changed: dict) -> None:
        _Gio, GLib = _gio()
        payload = {
            name: _to_variant(GLib, self._types[(interface, name)], value)
            for name, value in changed.items()
        }
        self._connection.emit_signal(
            None, OBJECT_PATH, PROPERTIES_INTERFACE, "PropertiesChanged",
            GLib.Variant("(sa{sv}as)", (interface, payload, [])))

    def close(self) -> None:
        if self._owner_id is not None:
            Gio, _GLib = _gio()
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = None


class WindowAdapter:
    """Map a ``MainWindow`` onto the controller protocol (duck-typed)."""

    def __init__(self, window) -> None:
        self._window = window

    def _owned(self) -> bool:
        window = self._window
        return bool(getattr(window, "now_playing", None)) and not bool(
            getattr(window, "external", False))

    def snapshot(self) -> MprisSnapshot:
        window = self._window
        path = getattr(window, "now_playing", None)
        if not self._owned() or not path:
            return MprisSnapshot()
        tracker = window.tracker
        duration = float(getattr(tracker, "duration", 0.0) or 0.0)
        media = getattr(window, "media", None)
        if not duration and media is not None:
            duration = float(getattr(media, "duration", 0.0) or 0.0)
        position = tracker.value()
        position = float(position) if isinstance(position, (int, float)) else 0.0
        queue = list(getattr(window, "queue", []) or [])
        index = queue.index(path) if path in queue else None
        return MprisSnapshot(
            playback_status=self._status(),
            title=pathlib.Path(path).stem,
            track_id=_track_id(path),
            length_us=int(max(0.0, duration) * 1_000_000),
            position_us=int(max(0.0, position) * 1_000_000),
            can_play=True,
            can_pause=True,
            can_go_next=index is not None and index + 1 < len(queue),
            # Previous always works: at the first track it restarts at 0 s.
            can_go_previous=True,
            can_seek=duration > 0 and bool(getattr(tracker, "known", False)),
            can_control=not bool(getattr(window, "busy", False)),
        )

    def _status(self) -> str:
        state = getattr(self._window, "device_state", "IDLE")
        if state in ("PLAYING", "BUFFERING", "PAUSED"):
            return state_labels.present(state).mpris
        tracker = self._window.tracker
        if getattr(tracker, "known", False):
            return "Playing" if getattr(tracker, "playing", False) else "Paused"
        return "Stopped"

    def play(self) -> None:
        if self._owned() and self.snapshot().playback_status != "Playing":
            self._window.toggle_play()

    def pause(self) -> None:
        if self._owned() and self.snapshot().playback_status == "Playing":
            self._window.toggle_play()

    def play_pause(self) -> None:
        if self._owned():
            self._window.toggle_play()

    def stop(self) -> None:
        if self._owned():
            self._window.action_stop()

    def next(self) -> None:
        if self._owned() and self.snapshot().can_go_next:
            self._window.on_next()

    def previous(self) -> None:
        if self._owned():
            self._window.on_prev()

    def seek(self, offset_us: int) -> None:
        if not (self._owned() and self.snapshot().can_seek):
            return
        position = self._window.tracker.value() or 0.0
        self._window.seek_to(max(0.0, position + offset_us / 1_000_000))

    def set_position(self, track_id: str, position_us: int) -> None:
        if self._owned() and track_id == _track_id(self._window.now_playing):
            self._window.seek_to(max(0.0, position_us / 1_000_000))

    def raise_window(self) -> None:
        try:
            self._window.present()
        except Exception:
            pass

    def quit_app(self) -> None:
        app = getattr(self._window, "app", None)
        if app is not None:
            app.quit()


def start(window, connection=None):
    """Publish MPRIS2 for *window*; return the service, or None if unavailable.

    Best-effort: a missing session bus, a non-Linux OS or a bus error must
    never prevent the application from running.
    """
    if platform.system() != "Linux":
        return None  # MPRIS2 is a Linux/desktop-bus feature (#266, optional per OS).
    try:
        Gio, _GLib = _gio()
        connection = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if connection is None:
            return None
        service = MprisService(GioBus(connection), WindowAdapter(window))
        service.publish()
        return service
    except Exception:
        return None
