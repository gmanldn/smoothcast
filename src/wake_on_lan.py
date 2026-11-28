"""Wake-on-LAN for sleeping mesh nodes (#427). Pure packet/flow logic; sockets and clock are injected.

Node record gains ``wol: {mac, broadcast}`` only when the user enables *Let other computers wake this one*.
``Wake`` sends from every awake node (deduped by a time window), counts down 60 s, then reports success or
the plain "can't be woken" message. BIOS setup help is out of scope.
"""
from __future__ import annotations

import re
from pathlib import Path

SETTING = "Let other computers wake this one"
TIMEOUT_S, DEDUPE_S, MAX_BROADCASTS = 60.0, 10.0, 8
_MAC = re.compile(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\Z", re.I)
_IP = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}\Z")


def norm_mac(mac) -> str | None:
    if not isinstance(mac, str) or not _MAC.match(mac.strip()):
        return None
    m = mac.strip().lower().replace("-", ":")
    return None if m in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") else m


def valid_broadcast(ip) -> bool:
    return isinstance(ip, str) and bool(_IP.match(ip)) and all(0 <= int(p) <= 255 for p in ip.split("."))


def magic_packet(mac: str) -> bytes:
    m = norm_mac(mac)
    if m is None:
        raise ValueError("bad MAC")
    return b"\xff" * 6 + bytes.fromhex(m.replace(":", "")) * 16


def node_record_field(enabled: bool, mac, broadcast) -> dict | None:
    """What a node advertises. Nothing unless the user opted in and the values are sane."""
    m = norm_mac(mac)
    if not enabled or m is None or not valid_broadcast(broadcast):
        return None
    return {"mac": m, "broadcast": broadcast}


def read_linux_mac(iface: str, root: str = "/sys/class/net") -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,15}", iface or ""):
        return None
    try:
        return norm_mac((Path(root) / iface / "address").read_text("ascii").strip())
    except (OSError, UnicodeError):
        return None


def send(mac: str, broadcast: str, sock_factory) -> bool:
    """One UDP/9 broadcast. ``sock_factory()`` returns a socket-like with setsockopt/sendto/close."""
    if not valid_broadcast(broadcast):
        return False
    try:
        pkt = magic_packet(mac)
        s = sock_factory()
        try:
            s.setsockopt(1, 6, 1)                      # SOL_SOCKET, SO_BROADCAST
            s.sendto(pkt, (broadcast, 9))
        finally:
            s.close()
        return True
    except (OSError, ValueError):
        return False


def asleep_message(name: str) -> str:
    return f"{name} is asleep and can't be woken remotely."


class Wake:
    def __init__(self, clock) -> None:
        self.clock, self.last, self.started = clock, {}, {}      # mac -> time

    def start(self, name: str, wol: dict | None, awake_senders: list, sender_fn) -> dict:
        """sender_fn(sender, mac, broadcast)->bool is called for each awake node. -> status dict."""
        if not wol or norm_mac(wol.get("mac")) is None or not valid_broadcast(wol.get("broadcast")):
            return {"state": "unavailable", "message": asleep_message(name)}
        mac, now = norm_mac(wol["mac"]), self.clock()
        if mac in self.last and now - self.last[mac] < DEDUPE_S:
            return {"state": "waking", "sent": 0, "message": self.progress(name, mac)}
        sent = sum(1 for s in awake_senders[:MAX_BROADCASTS] if _ok(sender_fn, s, mac, wol["broadcast"]))
        if sent == 0:                                    # nothing left the building: no dedupe stamp, no countdown
            return {"state": "unavailable", "message": asleep_message(name)}
        self.last[mac] = now
        self.started.setdefault(mac, now)
        return {"state": "waking", "sent": sent, "message": self.progress(name, mac)}

    def progress(self, name: str, mac: str) -> str:
        return f"Waking {name}… {int(self.clock() - self.started.get(mac, self.clock()))} s"

    def poll(self, name: str, mac: str, is_online: bool) -> dict:
        mac = norm_mac(mac) or mac
        t0 = self.started.get(mac)
        if t0 is None:
            return {"state": "idle"}
        if is_online:
            self.started.pop(mac, None)
            return {"state": "up", "message": f"{name} is awake."}
        if self.clock() - t0 >= TIMEOUT_S:
            self.started.pop(mac, None)
            return {"state": "timeout", "message": asleep_message(name)}
        return {"state": "waking", "message": self.progress(name, mac)}


def _ok(fn, *a) -> bool:
    try:
        return bool(fn(*a))
    except Exception:  # noqa: BLE001 - a failing wake call reports False
        return False
