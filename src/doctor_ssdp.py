"""SSDP self-test for ``doctor`` (#211 slice): one M-SEARCH, count the replies.

A reply proves multicast works both ways. Silence is only a WARN: a quiet network
and a blocked one look the same from here, so we say so instead of claiming either.
"""
from __future__ import annotations

import socket
import time
from typing import Callable

from doctor import PASS, WARN, Result

GROUP = ("239.255.255.250", 1900)
SEARCH = (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
          b'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n')


def ssdp(factory: Callable = socket.socket, wait: float = 1.5,
         clock: Callable[[], float] = time.monotonic) -> Result:
    name = "ssdp"
    fix = ("Check that a VPN or firewall allows multicast (UDP 1900); "
           "you can still add a receiver by IP.")
    try:
        with factory(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(SEARCH, GROUP)
            deadline = clock() + wait
            replies = 0
            while (left := deadline - clock()) > 0:
                sock.settimeout(left)
                try:
                    sock.recvfrom(2048)
                except socket.timeout:
                    break
                replies += 1
    except OSError as exc:
        return Result(name, WARN, f"Cannot send a discovery probe ({exc.__class__.__name__})", fix)
    if replies:
        return Result(name, PASS, f"{replies} device(s) answered the discovery probe")
    return Result(name, WARN, "No device answered the discovery probe; the network may be quiet or blocking multicast", fix)
