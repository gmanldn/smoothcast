"""Read-only snapshots of media playing on discovered LAN receivers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import playback_state
import math
import re
import time
from typing import Callable

import castctl
import dlna


ACTIVE_STATES = frozenset({"PLAYING", "BUFFERING", "PAUSED"})
MAX_RECEIVERS = 32
MAX_WORKERS = 4
TITLE_LIMIT = 160


def _safe_lan_host(value: object) -> str:
    host = str(value or "").strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if (address.version != 4 or not address.is_private or address.is_loopback
            or address.is_unspecified or address.is_link_local or address.is_multicast
            or address.is_reserved):
        return ""
    return str(address)


def _safe_title(value: object, fallback: str) -> str:
    title = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    title = " ".join(title.split())[:TITLE_LIMIT]
    return title or fallback


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed) if math.isfinite(parsed) else None


def _active_entry(protocol: str, receiver: str, host: str, info: object) -> dict | None:
    if not isinstance(info, dict):
        return None
    state = castctl.player_state(info)
    if state not in ACTIVE_STATES:
        return None
    return {
        "protocol": protocol,
        "receiver": _safe_title(receiver, "Unknown receiver"),
        "host": host,
        "title": _safe_title(info.get("title") or info.get("media_title") or playback_state.reported_title(info), "Media title unavailable"),
        "state": state,
        "position": _number(info.get("current_time")),
        "duration": _number(info.get("duration")),
    }


def snapshot(
    cast_devices: list[castctl.Device],
    dlna_renderers: list[dlna.Renderer],
    *,
    cast_status: Callable[..., dict | None] = castctl.info,
    dlna_status: Callable[[dlna.Renderer], dict | None] | None = None,
) -> list[dict]:
    """Poll at most 32 discovered receivers with four concurrent read-only calls.

    Cast receivers are addressed by their discovered IP rather than a friendly
    name, which can be duplicated or changed. Missing IPs and duplicate
    discovered endpoints are ignored. Inactive, offline and unrecognized
    states are omitted instead of guessing that media is playing.
    """
    jobs: list[tuple[str, str, str, Callable[[], dict | None]]] = []
    dlna_status = dlna_status or (lambda renderer: dlna.info(renderer, include_volume=False))
    seen: set[tuple[str, str]] = set()
    for device in cast_devices:
        host = _safe_lan_host(device.host)
        identity = ("Google Cast", host)
        if not host or identity in seen:
            continue
        seen.add(identity)
        jobs.append(("Google Cast", device.name, host,
                     lambda host=host: cast_status(host, timeout=10)))
    for renderer in dlna_renderers:
        host = str(renderer.host or "").strip()
        identity = ("DLNA", host)
        if not host or identity in seen:
            continue
        seen.add(identity)
        jobs.append(("DLNA", renderer.name, host,
                     lambda renderer=renderer: dlna_status(renderer)))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="sc-activity") as pool:
        futures = {pool.submit(job): (protocol, name, host)
                   for protocol, name, host, job in jobs[:MAX_RECEIVERS]}
        for future in as_completed(futures):
            protocol, name, host = futures[future]
            try:
                entry = _active_entry(protocol, name, host, future.result())
            except Exception:
                # One unresponsive or malformed receiver does not hide others.
                continue
            if entry is not None:
                results.append(entry)
    return sorted(results, key=lambda item: (item["receiver"].casefold(), item["protocol"]))


def portal_entries(entries: list[dict], local_host: str = "", updated: float | None = None) -> list[dict]:
    """Return privacy-trimmed dashboard rows without LAN addresses."""
    local_host = str(local_host or "").strip()
    # How old the receiver reading is, so viewers can advance a playing position.
    age_ms = (min(600_000, max(0, int((time.monotonic() - updated) * 1000)))
              if isinstance(updated, (int, float)) else None)
    rows = [
        {
            "protocol": str(item.get("protocol", "")),
            "receiver": str(item.get("receiver", "")),
            "title": str(item.get("title", "")),
            "state": str(item.get("state", "")),
            "position": item.get("position"),
            "duration": item.get("duration"),
            "is_local": bool(local_host and item.get("host") == local_host),
        }
        for item in entries[:MAX_RECEIVERS]
    ]
    if age_ms is not None:
        for row in rows:
            row["observed_age_ms"] = age_ms
    return rows
