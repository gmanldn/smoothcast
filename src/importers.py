"""Import watched/resume state from Jellyfin, Plex and Kodi export files (#435).

    smoothcast import jellyfin items.json  [--media DIR ...] [--apply]
    smoothcast import plex     library.csv [--media DIR ...] [--apply]
    smoothcast import kodi     MyVideos.db [--media DIR ...] [--apply]

Dry run by default: prints matched / ambiguous / unmatched counts and writes
nothing. ``--apply`` merges resume positions and "watched" events into
SmoothCast's settings, touching only those two keys. No live server access.

Matching, best first: the exported path exists here; a unique local file with
the same name; normalised title + year (films) or show + SxxEyy (episodes).
Several equally good local candidates are reported as ambiguous, never guessed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable
import csv
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sqlite3
import sys
import time

import cache_policy
import media_names
import watch_history

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100_000
MAX_CANDIDATES = 200_000
MEDIA_EXT = frozenset({".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mpeg", ".mpg",
                       ".wmv", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"})
KODI_VERSIONS = range(75, 200)  # MyVideos75 (Isengard) onwards share these tables.
TICKS_PER_SECOND = 10_000_000  # Jellyfin/Emby
WATCHED_FRACTION = 0.9


class ImportError_(Exception):
    """A user-facing import failure (unreadable or unsupported export)."""


@dataclass(frozen=True)
class Record:
    title: str
    kind: str = "movie"  # movie | episode
    year: int | None = None
    show: str = ""
    season: int | None = None
    episode: int | None = None
    path: str = ""
    position: float = 0.0
    duration: float | None = None
    watched: bool = False


@dataclass
class Report:
    matched: list[tuple[Record, str, str]] = field(default_factory=list)  # record, path, how
    ambiguous: list[tuple[Record, list[str]]] = field(default_factory=list)
    unmatched: list[Record] = field(default_factory=list)


# ------------------------------------------------------------------ parsers
def _int(value: object) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number


def _float(value: object) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and 0 <= number < 1e15 else 0.0  # Ticks are large.


def _read_bounded(path: Path) -> bytes:
    try:
        if Path(path).stat().st_size > MAX_INPUT_BYTES:
            raise ImportError_(f"{path} is larger than {MAX_INPUT_BYTES // 2**20} MiB")
        return Path(path).read_bytes()
    except OSError as exc:
        raise ImportError_(f"Cannot read {path}: {exc}") from exc


def parse_jellyfin(path: Path) -> list[Record]:
    """Jellyfin/Emby ``/Items`` JSON (``{"Items": [...]}`` or a bare list)."""
    try:
        payload = json.loads(_read_bounded(path).decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ImportError_(f"{path} is not Jellyfin JSON: {exc}") from exc
    items = payload.get("Items") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ImportError_("Unsupported Jellyfin export: expected an Items list of objects")
    records = []
    for item in items[:MAX_RECORDS]:
        kind = str(item.get("Type") or "").lower()
        if kind not in {"movie", "episode", "video", "audio"}:
            continue
        data = item.get("UserData") if isinstance(item.get("UserData"), dict) else {}
        runtime = _float(item.get("RunTimeTicks")) / TICKS_PER_SECOND or None
        records.append(Record(
            title=str(item.get("Name") or ""), kind="episode" if kind == "episode" else "movie",
            year=_int(item.get("ProductionYear")), show=str(item.get("SeriesName") or ""),
            season=_int(item.get("ParentIndexNumber")), episode=_int(item.get("IndexNumber")),
            path=str(item.get("Path") or ""),
            position=_float(data.get("PlaybackPositionTicks")) / TICKS_PER_SECOND,
            duration=runtime, watched=data.get("Played") is True))
    return records


_PLEX_COLUMNS = {
    "title": ("title", "name"),
    "year": ("year", "originally available", "release year"),
    "type": ("type", "media type"),
    "show": ("show", "series", "grandparent title", "show title"),
    "season": ("season", "season number", "parent index"),
    "episode": ("episode", "episode number", "index"),
    "offset": ("view offset", "viewoffset", "resume offset", "progress"),
    "count": ("view count", "viewcount", "play count", "watched"),
    "duration": ("duration",),
    "path": ("file", "part file", "path", "file path", "part file combined"),
}


def parse_plex(path: Path) -> list[Record]:
    """CSV from Plex export tools (e.g. WebTools/ExportTools); headers matched loosely.

    View offset and duration are milliseconds, as Plex stores them.
    """
    try:
        text = _read_bounded(path).decode("utf-8-sig")
    except UnicodeError as exc:
        raise ImportError_(f"{path} is not UTF-8 CSV: {exc}") from exc
    reader = csv.DictReader(text.splitlines())
    headers = {h.strip().lower(): h for h in (reader.fieldnames or []) if h}
    column = {key: next((headers[n] for n in names if n in headers), None)
              for key, names in _PLEX_COLUMNS.items()}
    if column["title"] is None:
        raise ImportError_("Unsupported Plex export: no Title column")

    def get(row: dict, key: str) -> str:
        name = column[key]
        return str(row.get(name) or "").strip() if name else ""
    records: list[Record] = []
    for row in reader:
        if len(records) >= MAX_RECORDS:
            break
        show = get(row, "show")
        kind = "episode" if show or get(row, "type").lower() == "episode" else "movie"
        count = get(row, "count").lower()
        duration = _float(get(row, "duration")) / 1000 or None
        records.append(Record(
            title=get(row, "title"), kind=kind, year=_int(get(row, "year")[:4]), show=show,
            season=_int(get(row, "season")), episode=_int(get(row, "episode")),
            path=get(row, "path"), position=_float(get(row, "offset")) / 1000,
            duration=duration, watched=count in {"yes", "true"} or (_int(count) or 0) > 0))
    return records


def parse_kodi(path: Path) -> list[Record]:
    """A *copy* of Kodi's MyVideosNN.db, opened read-only."""
    if not Path(path).is_file():
        raise ImportError_(f"Cannot read {path}")
    try:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ImportError_(f"Cannot open Kodi database: {exc}") from exc
    try:
        try:
            version = conn.execute("SELECT idVersion FROM version").fetchone()
        except sqlite3.Error as exc:
            raise ImportError_("Not a Kodi video database (no version table)") from exc
        if not version or version[0] not in KODI_VERSIONS:
            raise ImportError_(f"Unsupported Kodi database version {version and version[0]}")
        rows = conn.execute(f"""
            SELECT p.strPath, f.strFilename, f.playCount,
                   (SELECT timeInSeconds FROM bookmark b WHERE b.idFile = f.idFile AND b.type = 1),
                   (SELECT totalTimeInSeconds FROM bookmark b WHERE b.idFile = f.idFile AND b.type = 1),
                   m.c00, m.premiered, e.c00, e.c12, e.c13, t.c00
            FROM files f JOIN path p ON p.idPath = f.idPath
            LEFT JOIN movie m ON m.idFile = f.idFile
            LEFT JOIN episode e ON e.idFile = f.idFile
            LEFT JOIN tvshow t ON t.idShow = e.idShow
            WHERE m.idMovie IS NOT NULL OR e.idEpisode IS NOT NULL
            LIMIT {MAX_RECORDS}""").fetchall()
    except sqlite3.Error as exc:
        raise ImportError_(f"Unsupported Kodi database layout: {exc}") from exc
    finally:
        conn.close()
    records = []
    for folder, name, plays, resume, total, movie, premiered, ep_title, season, ep, show in rows:
        records.append(Record(
            title=str(movie or ep_title or ""), kind="episode" if show else "movie",
            year=_int(str(premiered or "")[:4]), show=str(show or ""),
            season=_int(season), episode=_int(ep),
            path=f"{folder or ''}{name or ''}", position=_float(resume),
            duration=_float(total) or None, watched=(_int(plays) or 0) > 0))
    return records


PARSERS = {"jellyfin": parse_jellyfin, "plex": parse_plex, "kodi": parse_kodi}


# ------------------------------------------------------------------ matching
def _norm(text: str) -> str:
    text = re.sub(r"['\u2019`]", "", media_names.clean_title(text).casefold())  # It's == Its
    return re.sub(r"[^0-9a-z]+", " ", text.replace("&", " and ")).strip()


def _basename(path: str) -> str:
    return (PureWindowsPath(path) if "\\" in path else PurePosixPath(path)).name


def _keys(path: str) -> list[tuple]:
    name = Path(path).name
    parent = Path(path).parent.name
    keys: list[tuple] = []
    episode = media_names.parse_episode(name, parent)
    if episode:
        show = episode[0] or media_names.clean_title(Path(path).parent.parent.name)
        keys.append(("episode", _norm(show), episode[1], episode[2]))
        return keys
    year = media_names.parse_year(name) or media_names.parse_year(parent)
    title = _norm(Path(name).stem)
    keys.append(("movie", title, year))
    if year is None or not title:
        keys.append(("movie", _norm(parent), media_names.parse_year(parent)))
    return keys


def _record_key(record: Record) -> tuple:
    if record.kind == "episode" and record.season is not None and record.episode is not None:
        return ("episode", _norm(record.show), record.season, record.episode)
    return ("movie", _norm(record.title), record.year)


class Library:
    """Index of local media files for matching."""

    def __init__(self, paths: Iterable[str]):
        self.paths = set()
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_key: dict[tuple, list[str]] = defaultdict(list)
        for path in paths:
            self.paths.add(path)
            self.by_name[Path(path).name.casefold()].append(path)
            for key in _keys(path):
                self.by_key[key].append(path)

    def match(self, record: Record) -> tuple[list[str], str]:
        if record.path and record.path in self.paths:
            return [record.path], "path"
        if record.path:
            same = self.by_name.get(_basename(record.path).casefold(), [])
            if same:
                return sorted(set(same)), "filename"
        key = _record_key(record)
        hits = self.by_key.get(key, [])
        if not hits and key[0] == "movie" and key[2] is not None:
            hits = self.by_key.get(("movie", key[1], None), [])  # Local file has no year.
        return sorted(set(hits)), "title"


def scan(folders: Iterable[Path]) -> list[str]:
    found: list[str] = []
    for folder in folders:
        for root, dirs, files in os.walk(Path(folder).expanduser()):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if Path(name).suffix.lower() in MEDIA_EXT:
                    found.append(str(Path(root) / name))
                    if len(found) >= MAX_CANDIDATES:
                        return found
    return found


def match_all(records: Iterable[Record], library: Library) -> Report:
    report = Report()
    for record in records:
        if not (record.watched or record.position > 0):
            continue  # Nothing to bring across.
        hits, how = library.match(record)
        if len(hits) == 1:
            report.matched.append((record, hits[0], how))
        elif hits:
            report.ambiguous.append((record, hits))
        else:
            report.unmatched.append(record)
    return report


# ------------------------------------------------------------------ apply
def apply(report: Report, config: dict, now: float | None = None) -> int:
    """Merge matched state into ``config`` (in place); return entries changed."""
    now = time.time() if now is None else now
    positions = dict(config.get("positions") or {})
    history = list(config.get("watch_history") or [])
    changed = 0
    for record, path, _how in report.matched:
        finished = record.watched or (
            record.duration and record.position >= WATCHED_FRACTION * record.duration)
        if finished:
            positions.pop(path, None)
            end = record.duration or record.position
            history = watch_history.record(history, path, "completed", end, now,
                                           duration=record.duration)
        else:
            positions[path] = round(record.position, 1)
            history = watch_history.record(history, path, "stop", record.position, now,
                                           duration=record.duration)
        changed += 1
    config["positions"] = positions
    config["watch_history"] = history
    return changed


def _save(config_file: Path, report: Report) -> int:
    import config_control
    defaults: dict[str, object] = {"positions": {}, "watch_history": []}
    cfg = config_control.load_file(config_file, defaults)
    changed = apply(report, cfg)
    # save_file merges only the keys changed here into whatever is on disk now.
    if not config_control.save_file(config_file, cfg):
        raise ImportError_(f"Could not save {config_file}; nothing was imported")
    return changed


def _library_folders(config_file: Path) -> list[Path]:
    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    folders = raw.get("library_folders") if isinstance(raw, dict) else None
    result = []
    for entry in folders if isinstance(folders, list) else []:
        value = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value:
            result.append(Path(value))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoothcast import",
        description="Bring watched/resume state from a Jellyfin, Plex or Kodi export. "
                    "Dry run unless --apply.")
    parser.add_argument("source", choices=sorted(PARSERS))
    parser.add_argument("file", type=Path, help="Jellyfin JSON, Plex CSV or a copy of Kodi MyVideos.db")
    parser.add_argument("--media", type=Path, action="append", default=[], metavar="DIR",
                        help="local media folder to match against (default: library folders)")
    parser.add_argument("--apply", action="store_true", help="write the matched state")
    parser.add_argument("-v", "--verbose", action="store_true", help="list each item")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    config_file = cache_policy.config_path()
    folders = args.media or _library_folders(config_file)
    if not folders:
        print("No media folders: pass --media DIR or add library folders in SmoothCast.",
              file=sys.stderr)
        return 2
    try:
        records = PARSERS[args.source](args.file)
        report = match_all(records, Library(scan(folders)))
    except ImportError_ as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(f"{len(report.matched)} matched, {len(report.ambiguous)} ambiguous, "
          f"{len(report.unmatched)} unmatched (of {len(records)} exported items)")
    if args.verbose:
        for record, path, how in report.matched:
            print(f"  matched ({how}): {record.title} -> {path}")
        for record, hits in report.ambiguous:
            print(f"  ambiguous: {record.title} -> {len(hits)} files")
        for record in report.unmatched:
            print(f"  unmatched: {record.title}")
    if not args.apply:
        print("Dry run: nothing written. Re-run with --apply to import.")
        return 0
    try:
        changed = _save(config_file, report)
    except ImportError_ as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(f"Imported state for {changed} item(s). Restart SmoothCast if it is open.")
    return 0
