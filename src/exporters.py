"""Export SmoothCast state as plain, portable files (#435).

``smoothcast export --to DIR`` writes queue.m3u8, queue.xspf, history.json,
rooms.json and preferences.json. Headless: never imports GTK, never contacts a
receiver, and never writes credentials (tokens, PINs, secrets) or session
state. Each file is replaced atomically, so an interrupted export leaves the
previous copy intact.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

import cache_policy
import room_checkpoint
import watch_history

FILES = ("queue.m3u8", "queue.xspf", "history.json", "rooms.json", "preferences.json")
XSPF_NS = "http://xspf.org/ns/0/"
MAX_XSPF_BYTES = 8 * 1024 * 1024
# Never export anything that could unlock a room, node or account.
_SECRET = re.compile(r"(token|password|passwd|secret|credential|api_?key|pin_code|private)", re.I)
# Watch state lives in history.json; window geometry is machine-local.
_NOT_PREFERENCES = frozenset({"watch_history", "positions", "window_width", "window_height",
                              "window_x", "window_y", "sleep_timer_deadline"})


class ExportError(Exception):
    """A user-facing export failure."""


def _clean_items(items: Iterable[str]) -> list[str]:
    result = []
    for item in items:
        if not isinstance(item, str) or not item or any(c in item for c in "\n\r\0"):
            raise ExportError("Queue contains an invalid media path")
        result.append(item)
    return result


def m3u8_text(items: Iterable[str], names: Mapping[str, str] | None = None) -> str:
    """Extended M3U with absolute paths, in queue order."""
    names = names or {}
    lines = ["#EXTM3U"]
    for item in _clean_items(items):
        title = " ".join(str(names.get(item) or Path(item).stem).split())
        lines += [f"#EXTINF:-1,{title}", item]
    return "\n".join(lines) + "\n"


def _location(item: str) -> str:
    return Path(item).as_uri() if Path(item).is_absolute() else quote(item)


def xspf_text(items: Iterable[str], names: Mapping[str, str] | None = None) -> str:
    names = names or {}
    ElementTree.register_namespace("", XSPF_NS)
    root = ElementTree.Element(f"{{{XSPF_NS}}}playlist", version="1")
    ElementTree.SubElement(root, f"{{{XSPF_NS}}}title").text = "SmoothCast queue"
    tracks = ElementTree.SubElement(root, f"{{{XSPF_NS}}}trackList")
    for item in _clean_items(items):
        track = ElementTree.SubElement(tracks, f"{{{XSPF_NS}}}track")
        ElementTree.SubElement(track, f"{{{XSPF_NS}}}location").text = _location(item)
        if names.get(item):
            ElementTree.SubElement(track, f"{{{XSPF_NS}}}title").text = names[item]
    ElementTree.indent(root)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ElementTree.tostring(root, encoding="unicode") + "\n")


def read_xspf(path: Path) -> list[str]:
    """Track locations in order; file:// URIs become local paths."""
    data = Path(path).read_bytes()
    if len(data) > MAX_XSPF_BYTES:
        raise ExportError("Playlist is too large")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ExportError("Playlist uses unsupported XML declarations")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ExportError(f"Playlist is not valid XSPF: {exc}") from exc
    result = []
    for node in root.iter(f"{{{XSPF_NS}}}location"):
        text = (node.text or "").strip()
        parsed = urlparse(text)
        result.append(unquote(parsed.path) if parsed.scheme == "file" else unquote(text))
    return result


def read_m3u8(path: Path) -> list[str]:
    """Entries in order, without resolving or dropping missing files."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def preferences(config: Mapping) -> dict:
    """User preferences without credentials, watch state or window geometry."""
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()
                    if not (isinstance(k, str) and _SECRET.search(k))}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    return {key: scrub(value) for key, value in config.items()
            if isinstance(key, str) and key not in _NOT_PREFERENCES and not _SECRET.search(key)}


def history(config: Mapping) -> dict:
    positions = config.get("positions")
    return {
        "schema_version": 1,
        "watch_history": watch_history.clean(config.get("watch_history")),
        "positions": {str(k): v for k, v in positions.items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if isinstance(positions, dict) else {},
    }


def _write_atomic(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def export(destination: Path, *, config: Mapping, queue: Iterable[str],
           names: Mapping[str, str] | None = None) -> list[Path]:
    """Write every export file into ``destination``; return the paths written."""
    destination = Path(destination).expanduser()
    items = _clean_items(queue)
    names = dict(names or {})
    contents = {
        "queue.m3u8": m3u8_text(items, names),
        "queue.xspf": xspf_text(items, names),
        "history.json": json.dumps(history(config), indent=2, ensure_ascii=False) + "\n",
        "rooms.json": json.dumps({"schema_version": 1, "rooms": [
            {"name": "This room", "queue": items,
             "display_names": {k: v for k, v in names.items() if k in items}}]},
            indent=2, ensure_ascii=False) + "\n",
        "preferences.json": json.dumps(preferences(config), indent=2, ensure_ascii=False,
                                       sort_keys=True) + "\n",
    }
    try:
        destination.mkdir(parents=True, exist_ok=True)
        written = []
        for name in FILES:
            target = destination / name
            _write_atomic(target, contents[name])
            written.append(target)
    except OSError as exc:
        raise ExportError(f"Cannot write export to {destination}: {exc}") from exc
    return written


def _load_config(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ExportError(f"Cannot read settings {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoothcast export",
        description="Write queue, history, rooms and preferences as plain files (no secrets).")
    parser.add_argument("--to", required=True, type=Path, metavar="DIR",
                        help="folder to write " + ", ".join(FILES))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    config_file = cache_policy.config_path()
    try:
        config = _load_config(config_file)
        checkpoint = room_checkpoint.load_checkpoint(config_file.parent / "room-checkpoint.json")
        if checkpoint.error:
            print(f"Room queue skipped: {checkpoint.error}", file=sys.stderr)
        written = export(args.to, config=config, queue=checkpoint.items,
                         names=dict(checkpoint.display_names))
    except ExportError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Exported {len(checkpoint.items)} queued item(s) to {args.to}:")
    for path in written:
        print(f"  {path.name}")
    return 0
