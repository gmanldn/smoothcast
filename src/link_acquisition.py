"""Bounded, host-authorised acquisition of single-video and BitTorrent links.

The guest supplies a canonical media identity, never a command, tracker,
webseed, path or credentials. External tools run only through an explicitly
configured host sandbox launcher. This is the room-host executor; remote
mesh scheduling and persistent cross-node job leases are separate concerns.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass, field
import guest_messages
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import unicodedata
import time
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from typing import Callable
import media_tools

MAX_LINK = 1500
MAX_BYTES = 2 * 1024**3
FREE_RESERVE = 512 * 1024**2
MAX_FILES = 128
MAX_PENDING = 4
MAX_RECORDS = 24
MAX_CACHE_BYTES = 8 * 1024**3
MAX_CACHE_DIRECTORIES = 128
MAX_SECONDS = 1800
MEDIA_SUFFIXES = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ts",
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav",
})
TERMINAL = frozenset({"ready", "failed", "cancelled", "delivery_uncertain"})
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
SEARCH_LIMIT = 10
SEARCH_OUTPUT_LIMIT = 512 * 1024
SEARCH_SECONDS = 20
_SEARCH_SLOT = threading.BoundedSemaphore(1)


class LinkError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Source:
    kind: str
    identity: str

    @property
    def url(self) -> str:
        if self.kind == "youtube":
            return "https://www.youtube.com/watch?v=" + self.identity
        return "magnet:?xt=urn:btih:" + self.identity

    @property
    def label(self) -> str:
        return "YouTube video" if self.kind == "youtube" else "BitTorrent media"


def parse_link(value: object) -> Source:
    """Canonicalise allowlisted links; discard every untrusted ancillary URL."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_LINK:
        raise LinkError(400, "Enter one YouTube video or magnet link (up to 1500 characters).")
    value = value.strip()
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise LinkError(400, "A link must not contain whitespace or control characters.")
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, max_num_fields=80)
        if parsed.scheme == "magnet":
            if parsed.netloc or parsed.path or parsed.fragment:
                raise ValueError
            xt = query.get("xt", [])
            if len(xt) != 1 or not xt[0].lower().startswith("urn:btih:"):
                raise LinkError(400, "Use a single BitTorrent v1 infohash magnet.")
            digest = xt[0][9:]
            if re.fullmatch(r"[0-9a-fA-F]{40}", digest):
                return Source("magnet", digest.lower())
            if re.fullmatch(r"[A-Za-z2-7]{32}", digest):
                return Source("magnet", base64.b32decode(digest.upper()).hex())
            raise LinkError(400, "The magnet infohash is invalid.")
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            raise ValueError
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if parsed.path == "/watch":
                ids = query.get("v", [])
                identity = ids[0] if len(ids) == 1 else ""
            elif parsed.path.startswith("/shorts/"):
                identity = parsed.path[len("/shorts/"):]
            else:
                identity = ""
        elif host == "youtu.be":
            identity = parsed.path.removeprefix("/")
        else:
            identity = ""
        if VIDEO_ID.fullmatch(identity):
            return Source("youtube", identity)
    except LinkError:
        raise
    except (ValueError, UnicodeError):
        pass
    raise LinkError(400, "Only a single HTTPS YouTube video or BitTorrent v1 magnet is supported.")


def _component(raw: bytes) -> str:
    """Conservative portable torrent path component, never a path expression."""
    try:
        name = raw.decode("utf-8")
    except (AttributeError, UnicodeError):
        raise LinkError(422, "Torrent contains an unsupported filename.") from None
    if (not name or name in {".", ".."} or len(raw) > 180
            or name.rstrip(" .") != name or any(ord(c) < 32 or c in '/\\:*?"<>|' for c in name)
            or name.split(".")[0].upper() in {
                "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}):
        raise LinkError(422, "Torrent contains an unsafe filename.")
    return name


class _Bencode:
    """Bounded parser retaining the exact bytes of the top-level info value."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.nodes = 0
        self.info: bytes | None = None

    def read(self, depth=0):
        self.nodes += 1
        if depth > 24 or self.nodes > 40000 or self.pos >= len(self.data):
            raise ValueError("metadata bounds")
        start = self.pos
        kind = self.data[self.pos:self.pos + 1]
        self.pos += 1
        if kind == b"i":
            end = self.data.index(b"e", self.pos)
            raw = self.data[self.pos:end]
            if len(raw) > 20 or not re.fullmatch(rb"0|-?[1-9][0-9]*", raw):
                raise ValueError("integer")
            self.pos = end + 1
            return int(raw)
        if kind in {b"l", b"d"}:
            items = [] if kind == b"l" else {}
            while self.data[self.pos:self.pos + 1] != b"e":
                if kind == b"l":
                    items.append(self.read(depth + 1))
                else:
                    key = self.read(depth + 1)
                    if not isinstance(key, bytes) or key in items:
                        raise ValueError("dictionary")
                    value_start = self.pos
                    items[key] = self.read(depth + 1)
                    if depth == 0 and key == b"info":
                        self.info = self.data[value_start:self.pos]
            self.pos += 1
            return items
        end = self.data.index(b":", start)
        raw = self.data[start:end]
        if len(raw) > 8 or not re.fullmatch(rb"0|[1-9][0-9]*", raw):
            raise ValueError("string length")
        length = int(raw)
        self.pos = end + 1 + length
        if self.pos > len(self.data):
            raise ValueError("truncated string")
        return self.data[end + 1:self.pos]


@dataclass(frozen=True)
class TorrentMedia:
    info: bytes
    relative: Path
    index: int
    size: int


def inspect_torrent(data: bytes, identity: str) -> TorrentMedia:
    """Authenticate metadata; choose the largest supported media file.

    Refuse unsafe paths, symlinks, ambiguous duplicate filenames, excessive
    total size and file count before starting payload download. Root tracker
    and webseed fields are not reused: only the authenticated info survives.
    """
    try:
        if len(data) > 2 * 1024**2:
            raise ValueError("metadata size")
        parser = _Bencode(data)
        root = parser.read()
        if parser.pos != len(data) or not isinstance(root, dict) or parser.info is None:
            raise ValueError("metadata")
        if hashlib.sha1(parser.info).hexdigest() != identity:  # BitTorrent v1 identity
            raise ValueError("infohash")
        info = root[b"info"]
        if not isinstance(info, dict) or info.get(b"private") or b"meta version" in info:
            raise ValueError("private or unsupported torrent")
        name = _component(info[b"name"])
        # Alternative UTF-8 names could be interpreted differently by a tool.
        if b"name.utf-8" in info or b"symlink path" in info or b"attr" in info:
            raise ValueError("alternate or linked path")
        files = info.get(b"files")
        if files is None:
            files = [{b"length": info[b"length"], b"path": [info[b"name"]]}]
            prefix = ()
        else:
            if b"length" in info:
                raise ValueError("ambiguous single/multi file")
            prefix = (name,)
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            raise ValueError("file count")
        if type(info.get(b"piece length")) is not int or not 0 < info[b"piece length"] <= 16 * 1024**2:
            raise ValueError("piece length")
        total = 0
        seen = set()
        candidates = []
        for index, item in enumerate(files, 1):
            if not isinstance(item, dict) or any(k in item for k in (b"attr", b"symlink path", b"path.utf-8")):
                raise ValueError("linked or alternate file")
            parts = item[b"path"]
            size = item[b"length"]
            if (not isinstance(parts, list) or not 1 <= len(parts) <= 12
                    or type(size) is not int or size < 0):
                raise ValueError("file metadata")
            relative = Path(*prefix, *(_component(part) for part in parts))
            key = str(relative).casefold()
            if key in seen:
                raise ValueError("duplicate filename")
            seen.add(key)
            total += size
            if total > MAX_BYTES:
                raise LinkError(413, "That torrent is larger than the 2 GiB download limit.")
            if size and relative.suffix.lower() in MEDIA_SUFFIXES:
                candidates.append((size, -index, relative))
        pieces = info.get(b"pieces")
        if (not isinstance(pieces, bytes) or not total
                or len(pieces) != 20 * ((total + info[b"piece length"] - 1) // info[b"piece length"])):
            raise ValueError("piece hashes")
        if not candidates:
            raise LinkError(422, "Torrent contains no supported audio or video file.")
        size, neg_index, relative = max(candidates, key=lambda item: item[:2])
        return TorrentMedia(parser.info, relative, -neg_index, size)
    except LinkError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, RecursionError, OverflowError):
        raise LinkError(422, "Torrent metadata is invalid, unsafe or unsupported.") from None


def _tree_bytes(root: Path) -> int:
    """Observe bounded staged size without following links or trusting names."""
    total = count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            count += 1
            path = Path(directory) / name
            info = path.lstat()
            if count > MAX_FILES * 2 or stat.S_ISLNK(info.st_mode):
                raise LinkError(422, "That download contains unsafe or too many files, so it was stopped.")
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise LinkError(422, "That download contains a file SmoothCast cannot play.")
    return total


def _reserve_cache_capacity(root: Path) -> None:
    """Bound retained staging without deleting a possibly queued/playing file.

    One writer and one active job reserve their full maximum payload size.
    Count even old, unindexed job directories; eviction of a journal receipt
    never implies permission to unlink the corresponding media.
    """
    total = count = 0
    for directory in root.iterdir():
        if not JOB_ID.fullmatch(directory.name):
            continue
        count += 1
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or count >= MAX_CACHE_DIRECTORIES:
            raise LinkError(507, "Acquisition cache requires owner review before more downloads.")
        total += _tree_bytes(directory)
        if total + MAX_BYTES > MAX_CACHE_BYTES:
            raise LinkError(507, "Acquisition cache is full. Existing media is preserved.")


def _safe_media(root: Path, path: Path) -> Path:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_BYTES
                or not path.resolve().is_relative_to(root.resolve())
                or path.suffix.lower() not in MEDIA_SUFFIXES):
            raise ValueError
    except (OSError, ValueError):
        raise LinkError(422, "The download did not produce a supported media file.") from None
    return path


def _search_text(value: object) -> str:
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 200
            or any(unicodedata.category(ch).startswith("C") for ch in value)):
        raise LinkError(400, "Enter a YouTube search of 1 to 200 characters.")
    return value.strip()


def _search_label(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value[:limit] if not unicodedata.category(ch).startswith("C")).strip()


def youtube_results(raw: bytes) -> list[dict]:
    """Project flat metadata onto a small, safe, single-video result contract."""
    if len(raw) > SEARCH_OUTPUT_LIMIT:
        raise LinkError(502, "YouTube returned too much search data.")
    results: list[dict] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(row, dict):
            continue
        identity = row.get("id")
        if (not isinstance(identity, str) or not VIDEO_ID.fullmatch(identity)
                or identity in seen or row.get("_type") in ("playlist", "multi_video")
                or row.get("ie_key") not in (None, "Youtube")
                or row.get("is_live") is True or row.get("live_status") in ("is_live", "is_upcoming")):
            continue
        title = _search_label(row.get("title"), 200)
        if not title:
            continue
        channel = _search_label(row.get("channel") or row.get("uploader"), 100)
        duration = row.get("duration")
        seconds = (int(duration) if type(duration) in (int, float)
                   and 0 < duration <= MAX_SECONDS * 48 and math.isfinite(duration) else None)
        results.append({"id": identity, "title": title, "channel": channel, "duration": seconds})
        seen.add(identity)
        if len(results) >= SEARCH_LIMIT:
            break
    return results


def _youtube_search_command(launcher: str, executable: str, text: str, cancelled) -> list[dict]:
    """Metadata only, bounded by a global slot, time and output budget."""
    if not _SEARCH_SLOT.acquire(blocking=False):
        raise LinkError(429, "YouTube search is busy. Try again shortly.")
    try:
        with tempfile.TemporaryDirectory(prefix="smoothcast-search-") as directory:
            with tempfile.TemporaryFile(dir=directory) as output:
                command = [launcher, executable, "--ignore-config", "--no-cache-dir",
                           "--no-cookies", "--no-cookies-from-browser", "--flat-playlist",
                           "--skip-download", "--dump-json", "--no-warnings",
                           "--socket-timeout", "8", "--retries", "0", "--extractor-retries", "0",
                           "--", f"ytsearch{SEARCH_LIMIT}:{text}"]
                kwargs = {"start_new_session": True} if os.name == "posix" else {}
                process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.DEVNULL, **kwargs)
                deadline = time.monotonic() + SEARCH_SECONDS
                try:
                    while process.poll() is None:
                        if cancelled():
                            raise LinkError(403, guest_messages.ACCESS_REMOVED)
                        if time.monotonic() >= deadline:
                            raise LinkError(504, "YouTube search timed out. Try again.")
                        if os.fstat(output.fileno()).st_size > SEARCH_OUTPUT_LIMIT:
                            raise LinkError(502, "YouTube returned too much search data.")
                        time.sleep(0.05)
                    if process.returncode:
                        raise LinkError(502, "YouTube search is unavailable right now.")
                    output.seek(0)
                    return youtube_results(output.read(SEARCH_OUTPUT_LIMIT + 1))
                finally:
                    if process.poll() is None:
                        try:
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except OSError:
                            pass
                        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise LinkError(503, guest_messages.YOUTUBE_OFF) from None
    finally:
        _SEARCH_SLOT.release()


ARCHIVE_CANDIDATE_LIMIT = 8
ARCHIVE_RESULT_LIMIT = 4
_ARCHIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
_ARCHIVE_LICENSE = re.compile(
    r"https?://creativecommons\.org/(?:licenses/(?:by|by-sa)/[1-4]\.0(?:/[a-z]{2})?"
    r"|licenses/publicdomain|publicdomain/(?:zero|mark)/1\.0)/?\Z", re.I)


def archive_candidates(raw: bytes, query: str) -> list[dict]:
    """Only explicit open/public-domain licence claims; popularity is downloads, not seeds."""
    if len(raw) > SEARCH_OUTPUT_LIMIT:
        raise LinkError(502, "Archive search returned too much data.")
    try:
        envelope = json.loads(raw)
        rows = envelope["response"]["docs"]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise LinkError(502, "Archive search returned invalid data.") from None
    if not isinstance(rows, list):
        raise LinkError(502, "Archive search returned invalid results.")
    terms = set(re.findall(r"\w+", query.casefold()))
    found = []
    seen = set()
    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        ident, license_url = row.get("identifier"), row.get("licenseurl")
        # Advanced Search may represent a single metadata value as an array.
        if isinstance(license_url, list) and len(license_url) == 1:
            license_url = license_url[0]
        if (not isinstance(ident, str) or not _ARCHIVE_ID.fullmatch(ident)
                or ident in seen or not isinstance(license_url, str)
                or not _ARCHIVE_LICENSE.fullmatch(license_url)):
            continue
        title = _search_label(row.get("title"), 200)
        if not title:
            continue
        overlap = len(terms & set(re.findall(r"\w+", title.casefold())))
        if not overlap:
            continue
        downloads = row.get("downloads")
        downloads = downloads if type(downloads) is int and 0 <= downloads <= 10**12 else 0
        seen.add(ident)
        found.append((overlap, downloads, ident, {
            "archive_id": ident, "title": title, "license": license_url,
            "downloads": downloads,
        }))
    found.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in found[:ARCHIVE_CANDIDATE_LIMIT]]


def archive_torrent_result(candidate: dict, data: bytes) -> dict:
    """Derive the exact v1 infohash and reuse the acquisition safety validator."""
    if len(data) > 2 * 1024**2:
        raise LinkError(422, "Archive torrent metadata is too large.")
    try:
        parser = _Bencode(data)
        parser.read()
        if parser.info is None or parser.pos != len(data):
            raise ValueError("missing info")
        digest = hashlib.sha1(parser.info).hexdigest()
    except (ValueError, TypeError, RecursionError, IndexError):
        raise LinkError(422, "Invalid Archive torrent metadata.") from None
    media = inspect_torrent(data, digest)
    return {**candidate, "id": digest, "size": media.size, "source": "Internet Archive"}


def _archive_fetch(launcher: str, curl: str, url: str, limit: int, cancelled,
                   deadline: float) -> bytes:
    """Fixed public HTTPS URLs only, executed through the qualified egress sandbox."""
    with tempfile.TemporaryDirectory(prefix="smoothcast-archive-") as directory:
        with tempfile.TemporaryFile(dir=directory) as output:
            seconds = max(1, min(6, int(deadline - time.monotonic())))
            command = [launcher, curl, "--disable", "--silent", "--show-error",
                       "--fail", "--location", "--max-redirs", "2", "--proto", "=https",
                       "--proto-redir", "=https", "--max-time", str(seconds),
                       "--max-filesize", str(limit), "--", url]
            kwargs = {"start_new_session": True} if os.name == "posix" else {}
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.DEVNULL, **kwargs)
            try:
                while process.poll() is None:
                    if cancelled():
                        raise LinkError(403, guest_messages.ACCESS_REMOVED)
                    if time.monotonic() >= deadline:
                        raise LinkError(504, "Archive search timed out.")
                    if os.fstat(output.fileno()).st_size > limit:
                        raise LinkError(502, "Archive response exceeded its size limit.")
                    time.sleep(0.05)
                if cancelled():
                    raise LinkError(403, guest_messages.ACCESS_REMOVED)
                if process.returncode == 28:
                    raise LinkError(504, "Archive search timed out.")
                if process.returncode:
                    raise LinkError(502, "Archive source unavailable.")
                output.seek(0)
                data = output.read(limit + 1)
                if len(data) > limit:
                    raise LinkError(502, "Archive response exceeded its size limit.")
                return data
            finally:
                if process.poll() is None:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except OSError:
                        pass
                    process.wait(timeout=5)


def _archive_search_command(launcher: str, curl: str, text: str, cancelled) -> list[dict]:
    if not _SEARCH_SLOT.acquire(blocking=False):
        raise LinkError(429, "External search is busy. Try again shortly.")
    try:
        terms = re.findall(r"[^\W_]+", text, re.UNICODE)[:12]
        if not terms:
            return []
        query = ('format:"Archive BitTorrent" AND mediatype:(movies OR audio) '
                 'AND licenseurl:* AND title:('
                 + " AND ".join('"' + term + '"' for term in terms) + ")")
        params = [("q", query), ("rows", "30"), ("output", "json"), ("sort[]", "downloads desc")]
        params += [("fl[]", field) for field in ("identifier", "title", "licenseurl", "downloads")]
        deadline = time.monotonic() + SEARCH_SECONDS
        raw = _archive_fetch(launcher, curl, "https://archive.org/advancedsearch.php?" + urlencode(params),
                             SEARCH_OUTPUT_LIMIT, cancelled, deadline)
        results = []
        seen = set()
        failure: LinkError | None = None
        for candidate in archive_candidates(raw, text):
            if cancelled():
                raise LinkError(403, guest_messages.ACCESS_REMOVED)
            if deadline - time.monotonic() < 1:
                failure = LinkError(504, "Archive search timed out before all candidates could be checked.")
                break
            ident = quote(candidate["archive_id"], safe="")
            url = f"https://archive.org/download/{ident}/{ident}_archive.torrent"
            try:
                data = _archive_fetch(launcher, curl, url, 2 * 1024**2, cancelled, deadline)
            except LinkError as exc:
                if exc.status not in (502, 503, 504):
                    raise
                failure = exc
                continue
            try:
                row = archive_torrent_result(candidate, data)
            except LinkError as exc:
                if exc.status not in (413, 422):
                    raise
                continue
            if row["id"] not in seen:
                seen.add(row["id"])
                results.append(row)
                if len(results) >= ARCHIVE_RESULT_LIMIT:
                    break
        if cancelled():
            raise LinkError(403, guest_messages.ACCESS_REMOVED)
        if not results and failure is not None:
            raise failure
        return results
    except (OSError, subprocess.TimeoutExpired):
        raise LinkError(503, guest_messages.ARCHIVE_OFF) from None
    finally:
        _SEARCH_SLOT.release()


class CommandProvider:
    """Real command adapters; only an owner-configured isolation launcher may run them.

    Launcher contract: receive executable + argv, deny local/private network
    destinations and filesystem access outside staging/required runtime,
    enforce a hard disk quota and terminate the entire process tree. The
    application cannot verify an arbitrary launcher's OS security policy.
    Never enable this on an untrusted host without that policy.
    """
    def __init__(self, kinds=(), *, launcher=None):
        raw = launcher or os.environ.get("SMOOTHCAST_LINK_SANDBOX", "")
        if not raw:
            try:
                import link_provision
                raw = link_provision.default_launcher()
            except Exception:
                raw = ""
        self.launcher = (str(raw) if raw and Path(raw).is_absolute()
                         and Path(raw).is_file() and os.access(raw, os.X_OK) else "")
        self.tools = {kind: shutil.which(tool) for kind, tool in
                      (("youtube", "yt-dlp"), ("magnet", "aria2c"))}
        self.probe = media_tools.find_media_tool("ffprobe")
        self.archive_curl = shutil.which("curl")
        self.kinds = frozenset(kinds)

    def _isolation_verified(self) -> bool:
        """A passing ``--link-check --qualify`` for this exact launcher file (#588)."""
        try:
            import link_sandbox_probe
            return bool(self.launcher) and link_sandbox_probe.is_verified(self.launcher)
        except Exception:
            return False

    def readiness(self) -> dict:
        """Cheap local prerequisites only; never runs programs or contacts a source."""
        return {kind: {
            "enabled_by_owner": kind in self.kinds,
            "engine_present": bool(self.tools[kind]),
            "probe_present": bool(self.probe),
            "launcher_configured": bool(self.launcher),
            "isolation_verified": self._isolation_verified(),
            "missing": [name for name, present in (
                ("yt-dlp" if kind == "youtube" else "aria2c", self.tools[kind]),
                ("ffprobe", self.probe), ("owner-configured isolation launcher", self.launcher),
                ("qualified isolation (run smoothcast --link-check --qualify)",
                 not self.launcher or self._isolation_verified()),
            ) if not present],
        } for kind in ("youtube", "magnet")}

    def capabilities(self) -> dict:
        return {kind: row["enabled_by_owner"] and not row["missing"]
                for kind, row in self.readiness().items()}

    def search_youtube(self, value: object, cancelled) -> list[dict]:
        text = _search_text(value)
        if not self.capabilities().get("youtube"):
            raise LinkError(503, guest_messages.YOUTUBE_OFF)
        return _youtube_search_command(self.launcher, str(self.tools["youtube"]), text, cancelled)

    def magnet_search_available(self) -> bool:
        return bool(self.archive_curl and self.capabilities().get("magnet"))

    def search_magnets(self, value: object, cancelled) -> list[dict]:
        if not isinstance(value, str) or not 3 <= len(value.strip()) <= 200:
            raise LinkError(400, "Enter a search of 3 to 200 characters.")
        text = _search_text(value)
        if not self.magnet_search_available():
            raise LinkError(503, "Archive search is unavailable in this room. Try again later.")
        return _archive_search_command(self.launcher, str(self.archive_curl), text, cancelled)

    def readiness_text(self, kind: str) -> str:
        row = self.readiness()[kind]
        if row["missing"]:
            return "Missing: " + ", ".join(row["missing"]) + "."
        return ("Worker configured; OS isolation is not verified. "
                + ("Enabled on next room restart." if row["enabled_by_owner"] else "Owner permission is off."))

    def _run(self, executable, args, directory, cancelled, progress, deadline):
        if cancelled():
            raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
        if shutil.disk_usage(directory).free < FREE_RESERVE + MAX_BYTES:
            raise LinkError(507, "There is not enough space on the SmoothCast computer for that download.")
        command = [self.launcher, str(executable), *args]
        kwargs = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        except OSError:
            raise LinkError(503, guest_messages.LINK_DOWNLOADS_UNAVAILABLE) from None

        def read_progress():
            assert process.stdout is not None
            try:
                while line := process.stdout.readline(4096):
                    yt = re.search(rb"SC_PROGRESS ([0-9]+) ([0-9]+|NA)", line)
                    bt = re.search(rb"\[#\w+ ([0-9]+)B/([0-9]+)B", line)
                    match = yt or bt
                    if match:
                        done = int(match[1])
                        total = int(match[2]) if match[2].isdigit() else None
                        progress(done, total)
            except (OSError, ValueError):
                return
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        try:
            while process.poll() is None:
                if cancelled():
                    raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
                if time.monotonic() >= deadline:
                    raise LinkError(504, "The download took too long and was stopped.")
                if _tree_bytes(directory) > MAX_BYTES or shutil.disk_usage(directory).free < FREE_RESERVE:
                    raise LinkError(507, "The SmoothCast computer has reached its download storage limit.")
                time.sleep(0.25)
            if process.returncode:
                raise LinkError(502, "The download failed, or the source is unavailable.")
            if _tree_bytes(directory) > MAX_BYTES:
                raise LinkError(413, "The downloaded file is larger than the download limit.")
        finally:
            if process.poll() is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    pass
                process.wait(timeout=5)
            reader.join(timeout=1)
            if process.stdout is not None:
                process.stdout.close()

    def acquire(self, source: Source, directory: Path, stage, progress, cancelled) -> Path:
        if not self.capabilities().get(source.kind):
            raise LinkError(503, guest_messages.LINK_DOWNLOADS_UNAVAILABLE)
        deadline = time.monotonic() + MAX_SECONDS
        tool = self.tools[source.kind]
        if source.kind == "youtube":
            stage("downloading")
            self._run(tool, [
                "--ignore-config", "--no-cache-dir", "--no-playlist", "--no-cookies",
                "--no-cookies-from-browser", "--match-filter", "!is_live",
                "--max-filesize", str(MAX_BYTES), "--socket-timeout", "20",
                "--retries", "2", "--format", "best[ext=mp4]/best",
                "--restrict-filenames", "--output", "%(title).100B.%(ext)s",
                "--newline", "--progress", "--progress-template",
                "download:SC_PROGRESS %(progress.downloaded_bytes)s %(progress.total_bytes)s",
                "--", source.url,
            ], directory, cancelled, progress, deadline)
            candidates = [p for p in directory.iterdir() if p.suffix.lower() in MEDIA_SUFFIXES]
            if len(candidates) != 1:
                raise LinkError(422, "The source did not produce exactly one media file.")
            path = _safe_media(directory, candidates[0])
        else:
            # Do not pass guest-supplied trackers/webseeds to the worker.
            # First download only metadata, authenticate and inspect it.
            common = [
                "--no-conf=true", "--enable-rpc=false", "--seed-time=0",
                "--enable-dht=true", "--enable-dht6=false", "--bt-enable-lpd=false",
                "--enable-peer-exchange=false", "--file-allocation=none",
                "--bt-max-peers=32", "--max-overall-download-limit=8M",
                "--max-overall-upload-limit=128K", "--summary-interval=1",
                "--human-readable=false", "--bt-stop-timeout=120",
                "--dht-file-path=" + str(directory / "dht.dat"),
                "--dir=" + str(directory), "--allow-overwrite=false",
                "--auto-file-renaming=false",
            ]
            stage("resolving")
            self._run(tool, [*common, "--bt-metadata-only=true", "--bt-save-metadata=true",
                             "--", source.url], directory, cancelled, progress, deadline)
            metadata = directory / (source.identity + ".torrent")
            if not metadata.is_file() or metadata.is_symlink() or metadata.stat().st_size > 2 * 1024**2:
                raise LinkError(422, "No valid BitTorrent metadata was received.")
            selected = inspect_torrent(metadata.read_bytes(), source.identity)
            clean = directory / "verified-source.torrent"
            clean.write_bytes(b"d4:info" + selected.info + b"e")
            payload = directory / "payload"
            payload.mkdir(mode=0o700)
            stage("downloading")
            progress(0, selected.size)
            download_options = [opt for opt in common if not opt.startswith("--dir=")]
            self._run(tool, [*download_options, "--dir=" + str(payload),
                             "--select-file=" + str(selected.index),
                             "--check-integrity=true", "--", str(clean)],
                      directory, cancelled, progress, deadline)
            path = _safe_media(payload, payload / selected.relative)
            if path.stat().st_size != selected.size:
                raise LinkError(422, "Torrent media size does not match verified metadata.")
        stage("verifying")
        if cancelled():
            raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
        # ffprobe receives a local file, with network protocols disabled.
        try:
            result = subprocess.run(
                [self.launcher, str(self.probe), "-v", "error", "-protocol_whitelist", "file,pipe",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                cwd=directory, capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise LinkError(422, "The acquired media could not be verified.") from None
        if result.returncode or not {b"audio", b"video"} & set(result.stdout.splitlines()):
            raise LinkError(422, "The acquired file has no readable audio or video stream.")
        return path


@dataclass
class _Job:
    id: str
    owner: str
    request: str
    source: Source
    stage: str = "pending"
    title: str = ""
    received: int | None = None
    total: int | None = None
    rate: int | None = None
    measured_at: float = 0.0
    error: str = ""
    # Verified retained media (#590): byte size and SHA-256 taken before the first
    # queue dispatch. The file is found again by content, never by a stored name.
    size: int = 0
    digest: str = ""
    home: str = ""  # id of the job whose directory holds the media (reuse jobs)
    cancel: threading.Event = field(default_factory=threading.Event)


JOURNAL_SCHEMA = 1
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(path: Path, cancelled: Callable[[], bool]) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            if cancelled():
                raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
            digest.update(chunk)
    return digest.hexdigest()
JOURNAL_BYTES = 64 * 1024
JOB_ID = re.compile(r"[0-9a-f]{24}\Z")


class _JobJournal:
    """Private single-writer receipt log; a restart never replays delivery.

    Hold the OS lock until the previous worker exits, not merely until its
    room closes. No session keys, requests, titles or file paths are stored.
    """
    def __init__(self, root: Path):
        import cache_privacy

        self.path = root / "acquisition-journal.json"
        self.fd = None
        cache_privacy.ensure_private_directory(root)
        lock = root / ".acquisition.lock"
        if lock.is_symlink():
            raise ValueError("Unsafe acquisition lock")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0), 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Invalid acquisition lock")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                if metadata.st_uid != os.getuid():
                    raise ValueError("Acquisition lock belongs to another user")
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)

    def load(self):
        import json

        if self.path.is_symlink():
            raise ValueError("Unsafe acquisition journal")
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
        except FileNotFoundError:
            return []
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_size > JOURNAL_BYTES):
                raise ValueError("Invalid acquisition journal file")
            if os.name != "nt":
                if metadata.st_uid != os.getuid():
                    raise ValueError("Acquisition journal belongs to another user")
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                content = stream.read(JOURNAL_BYTES + 1)
            if len(content) > JOURNAL_BYTES:
                raise ValueError("Acquisition journal exceeds limit")
            data = json.loads(content)
        finally:
            if fd >= 0:
                os.close(fd)
        if (not isinstance(data, dict) or type(data.get("schema")) is not int
                or data["schema"] != JOURNAL_SCHEMA or not isinstance(data.get("jobs"), list)
                or len(data["jobs"]) > MAX_RECORDS):
            raise ValueError("Unsupported acquisition journal")
        jobs = []
        seen = set()
        for record in data["jobs"]:
            if not isinstance(record, dict):
                raise ValueError("Invalid acquisition receipt")
            ident, kind, identity, stage = (record.get(k) for k in ("id", "kind", "identity", "stage"))
            if (not isinstance(ident, str) or not JOB_ID.fullmatch(ident) or ident in seen
                    or not isinstance(kind, str) or kind not in {"youtube", "magnet"}
                    or not isinstance(identity, str) or not isinstance(stage, str)
                    or stage not in TERMINAL | {"pending", "resolving", "downloading", "verifying", "queueing"}):
                raise ValueError("Invalid acquisition receipt")
            source = Source(kind, identity)
            if parse_link(source.url) != source:
                raise ValueError("Noncanonical acquisition source")
            seen.add(ident)
            error = ""
            if stage in {"queueing", "delivery_uncertain"}:
                stage = "delivery_uncertain"
                error = "Previous queue delivery was not confirmed. Check recovered Up Next; not replayed."
            elif stage == "ready":
                error = "Previously accepted by the room; check recovered Up Next."
            elif stage not in TERMINAL:
                stage = "failed"
                error = "Interrupted by a room restart. Submit a new authorised request to retry."
            elif stage == "failed":
                error = "Previous acquisition failed. Submit a new authorised request to retry."
            job = _Job(ident, "", "", source, stage=stage, title=source.label, error=error)
            size, digest, home = (record.get(k) for k in ("size", "sha256", "home"))
            if (stage == "ready" and type(size) is int and 0 < size <= MAX_BYTES
                    and isinstance(digest, str) and SHA256.fullmatch(digest)
                    and (home is None or (isinstance(home, str) and JOB_ID.fullmatch(home)))):
                job.size, job.digest, job.home = size, digest, home or ""
            jobs.append(job)
        return jobs

    def save(self, jobs):
        import cache_privacy

        if self.fd is None:
            raise OSError("Acquisition journal is closed")
        cache_privacy.write_private_json_atomic(self.path, {
            "schema": JOURNAL_SCHEMA,
            "jobs": [{"id": job.id, "kind": job.source.kind, "identity": job.source.identity,
                      "stage": job.stage,
                      # Content identity only: no file name or path is persisted.
                      **({"size": job.size, "sha256": job.digest,
                          **({"home": job.home} if job.home else {})}
                         if job.digest else {})} for job in jobs],
        })


class LinkJobs:
    """One bounded worker per room; snapshots expose no URL, hash or path."""
    def __init__(self, root: Path, provider, deliver: Callable, owner_active: Callable):
        self.root = Path(root)
        self.provider = provider
        self.deliver = deliver
        self.owner_active = owner_active
        self._lock = threading.RLock()
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._requests: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._revision = 0
        self._journal = None
        self._journal_error = False
        try:
            self._journal = _JobJournal(self.root)
            self._jobs.update((job.id, job) for job in self._journal.load())
        except (OSError, ValueError, RecursionError):
            # Preserve damaged or busy storage; never start another writer.
            self._journal_error = True
            self._release_journal()

    def capabilities(self):
        if self._journal_error or self._closed:
            return {"youtube": False, "magnet": False}
        return self.provider.capabilities()

    def search_available(self) -> bool:
        if self._journal_error or self._closed:
            return False
        available = getattr(self.provider, "search_available", None)
        return bool(available()) if callable(available) else bool(
            self.capabilities().get("youtube") and callable(getattr(self.provider, "search_youtube", None)))

    def search_youtube(self, owner: str, value: object) -> list[dict]:
        text = _search_text(value)
        search = getattr(self.provider, "search_youtube", None)
        if not self.search_available() or not callable(search):
            raise LinkError(503, guest_messages.YOUTUBE_OFF)

        def cancelled():
            return self._closed or not self.owner_active(owner)

        if cancelled():
            raise LinkError(403, guest_messages.ACCESS_REMOVED)
        results = search(text, cancelled)
        if cancelled():
            raise LinkError(403, guest_messages.ACCESS_REMOVED)
        return results

    def magnet_search_available(self) -> bool:
        available = getattr(self.provider, "magnet_search_available", None)
        return bool(not self._journal_error and not self._closed
                    and callable(available) and available())

    def search_magnets(self, owner: str, value: object) -> list[dict]:
        search = getattr(self.provider, "search_magnets", None)
        if not self.magnet_search_available() or not callable(search):
            raise LinkError(503, "Archive search is unavailable in this room.")
        def cancelled():
            return self._closed or not self.owner_active(owner)
        if cancelled():
            raise LinkError(403, guest_messages.ACCESS_REMOVED)
        results = search(value, cancelled)
        if cancelled():
            raise LinkError(403, guest_messages.ACCESS_REMOVED)
        return results

    def storage_available(self):
        return not self._journal_error and not self._closed

    def _save(self):
        """Caller holds _lock. A failed write prevents new external work."""
        if self._journal_error or self._journal is None:
            return False
        try:
            self._journal.save(self._jobs.values())
            return True
        except (OSError, ValueError):
            self._journal_error = True
            for job in self._jobs.values():
                if job.stage == "pending":
                    self._change(job, stage="failed", error="The SmoothCast computer could not save the download. Try again shortly.")
            self._revision += 1
            return False

    def _release_journal(self):
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def submit(self, owner: str, value: object, request: object) -> str:
        source = parse_link(value)
        if not isinstance(request, str) or not REQUEST_ID.fullmatch(request):
            raise LinkError(400, "Submission identifier is invalid.")
        if not self.owner_active(owner):
            raise LinkError(401, guest_messages.ACCESS_REMOVED)
        with self._lock:
            if self._closed:
                raise LinkError(503, "The room is shutting down.")
            if self._journal_error:
                raise LinkError(503, "The SmoothCast computer could not save the download. Try again shortly.")
            if not self.capabilities().get(source.kind):
                raise LinkError(503, guest_messages.LINK_DOWNLOADS_UNAVAILABLE)
            receipt = self._requests.get((owner, request))
            if receipt is not None:
                job = self._jobs.get(receipt)
                if job is not None:
                    if job.source != source:
                        raise LinkError(409, "Submission identifier was already used for another link.")
                    return job.id
            return self._enqueue(owner, source, request)

    def retry(self, owner: str, job_id: object) -> str:
        """One explicit retry of a failed/cancelled row; never a second download.

        The canonical source is already stored privately, so no raw URL is needed.
        A safe local fallback reuses verified retained media when it exists.
        """
        if not self.owner_active(owner):
            raise LinkError(401, guest_messages.ACCESS_REMOVED)
        with self._lock:
            if self._closed:
                raise LinkError(503, "The room is shutting down.")
            if self._journal_error:
                raise LinkError(503, "The SmoothCast computer could not save the download. Try again shortly.")
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            if job is None or job.owner != owner:
                raise LinkError(404, "That download is not available to retry.")
            if job.stage not in {"failed", "cancelled"}:
                raise LinkError(409, "Only a failed or cancelled download can be retried.")
            if not self.capabilities().get(job.source.kind):
                raise LinkError(503, guest_messages.LINK_DOWNLOADS_UNAVAILABLE)
            return self._enqueue(owner, job.source, job.request)

    def _enqueue(self, owner: str, source: Source, request: str) -> str:
        """Caller holds _lock: create or join the one attempt for *source*."""
        same = [j for j in self._jobs.values() if j.source == source]
        for job in same:
            if job.stage not in {"failed", "cancelled", "ready", "delivery_uncertain"}:
                self._remember_request(owner, request, job.id)
                return job.id  # still working: one external download per source
        retained = next((j for j in reversed(same) if j.stage == "ready" and j.digest), None)
        if retained is None:
            for job in same:
                if job.stage not in {"failed", "cancelled"}:
                    self._remember_request(owner, request, job.id)
                    return job.id
        if sum(j.stage not in TERMINAL for j in self._jobs.values()) >= MAX_PENDING:
            raise LinkError(429, "The download queue is full. Try again when one of the current downloads finishes.")
        previous_jobs = self._jobs.copy()
        previous_requests = self._requests.copy()
        while len(self._jobs) >= MAX_RECORDS:
            # Never forget an ambiguous dispatch merely to free a slot.
            expired = next((j for j in self._jobs.values()
                            if j.stage in TERMINAL - {"delivery_uncertain"}), None)
            if expired is None:
                raise LinkError(429, "The download queue is full.")
            self._jobs.pop(expired.id)
            for key, value in tuple(self._requests.items()):
                if value == expired.id:
                    self._requests.pop(key)
        job = _Job(secrets.token_hex(12), owner, request, source, title=source.label)
        if retained is not None:  # deliberate re-queue: no second download (#590)
            job.size, job.digest = retained.size, retained.digest
            job.home = retained.home or retained.id
        self._jobs[job.id] = job
        self._remember_request(owner, request, job.id)
        if not self._save():
            self._jobs, self._requests = previous_jobs, previous_requests
            raise LinkError(503, "The download could not be recorded, so nothing was downloaded. Try again shortly.")
        self._revision += 1
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="room-link-acquisition", daemon=True)
            self._worker.start()
        return job.id

    def _remember_request(self, owner, request, job_id):
        # Keep bounded replay aliases even when another guest originally
        # submitted the canonical source.
        key = (owner, request)
        self._requests[key] = job_id
        self._requests.move_to_end(key)
        while len(self._requests) > 256:
            self._requests.popitem(last=False)

    def _change(self, job, **values):
        with self._lock:
            for key, value in values.items():
                setattr(job, key, value)
            self._revision += 1

    def _progress(self, job, received, total):
        if type(received) is not int or not 0 <= received <= MAX_BYTES:
            return
        total = total if type(total) is int and received <= total <= MAX_BYTES and total else None
        with self._lock:
            now = time.monotonic()
            elapsed = now - job.measured_at
            rate = (int((received - job.received) / elapsed)
                    if job.received is not None and received >= job.received and elapsed >= 0.25 else None)
            self._change(job, received=received, total=total, rate=rate, measured_at=now)

    def _work(self):
        while True:
            with self._lock:
                job = next((j for j in self._jobs.values() if j.stage == "pending"), None)
                if job is None or self._closed or self._journal_error:
                    self._worker = None
                    if self._closed:
                        self._release_journal()
                    return
                self._change(job, stage="resolving")
                if not self._save():
                    self._change(job, stage="failed", error="Acquisition receipt could not be saved.")
                    continue
            directory = self.root / (job.home or job.id)
            delivered = False
            reused: Path | None = None

            def cancelled():
                return job.cancel.is_set() or not self.owner_active(job.owner)

            def stage(value):
                if cancelled():
                    raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
                self._change(job, stage=value, received=None, total=None, rate=None, measured_at=0.0)

            try:
                if cancelled():
                    raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
                if job.home:
                    reused = self._verified_retained(job, directory, cancelled)
                if reused is not None:
                    path = reused
                else:
                    if job.home:  # retained file failed verification: acquire afresh
                        self._change(job, size=0, digest="", home="")
                        directory = self.root / job.id
                    _reserve_cache_capacity(self.root)
                    directory.mkdir(mode=0o700)
                    path = self.provider.acquire(job.source, directory, stage,
                                                 lambda n, total: self._progress(job, n, total), cancelled)
                    path = _safe_media(directory, Path(path))
                    stage("verifying")
                    self._change(job, size=path.stat().st_size, digest=_sha256(path, cancelled))
                # Crossing the queue-delivery boundary and accepting cancel
                # are mutually exclusive. The queue authority checks the
                # owner's live session again when it receives the request.
                with self._lock:
                    if cancelled() or self._closed:
                        raise LinkError(409, guest_messages.DOWNLOAD_CANCELLED)
                    if self._journal_error:
                        raise LinkError(503, "The SmoothCast computer could not save the download. Try again shortly.")
                    title = "".join(c for c in path.name if c.isprintable())[:120]
                    title = title.replace(job.source.identity, "[source]") or job.source.label
                    self._change(job, stage="queueing", title=title,
                                 received=path.stat().st_size, total=path.stat().st_size, rate=None)
                    # Durable intent precedes the irreversible queue call.
                    if not self._save():
                        raise LinkError(503, "Queue delivery receipt could not be saved.")
                    delivered = True
                # Keep the file if a dispatch may have happened. A lost
                # response must not remove media already in the queue.
                self.deliver(job.owner, path)
                with self._lock:
                    self._change(job, stage="ready")
                    if not self._save():
                        self._change(job, stage="delivery_uncertain",
                                     error="Queue accepted media but its receipt could not be saved. Check Up Next.")
            except LinkError as exc:
                self._change(job, stage="cancelled" if cancelled() and not delivered else
                             "delivery_uncertain" if delivered else "failed", error=exc.message, rate=None)
            except Exception:
                self._change(job, stage="delivery_uncertain" if delivered else
                             "cancelled" if cancelled() else "failed",
                             error="Queue delivery not confirmed; check Up Next." if delivered else
                             "Acquisition could not finish on this host.", rate=None)
            finally:
                if not delivered and reused is None and not job.home:
                    shutil.rmtree(directory, ignore_errors=True)
                with self._lock:
                    if job.stage != "ready":
                        self._save()

    def _verified_retained(self, job, directory: Path, cancelled) -> Path | None:
        """The previously acquired file, found by size and content hash."""
        try:
            candidates = []
            for index, (folder, _dirs, names) in enumerate(os.walk(directory)):
                if index > MAX_FILES:
                    break
                candidates += [Path(folder) / name for name in names]
            for path in candidates[:MAX_FILES]:
                try:
                    _safe_media(directory, path)
                    if path.stat().st_size == job.size and _sha256(path, cancelled) == job.digest:
                        return path
                except LinkError:
                    if cancelled():
                        raise
        except OSError:
            pass
        return None

    def snapshot(self, owner=None):
        with self._lock:
            return [{"id": j.id, "kind": j.source.kind, "title": j.title, "stage": j.stage,
                     "received": j.received, "total": j.total, "rate": j.rate, "error": j.error,
                     "executor": "room host",
                     "can_cancel": bool(j.owner) and j.owner == owner and j.stage not in TERMINAL | {"queueing"},
                     "can_retry": bool(j.owner) and j.owner == owner and j.stage in {"failed", "cancelled"}}
                    for j in self._jobs.values()]

    def revision(self):
        with self._lock:
            return self._revision

    def cancel(self, owner, job_id):
        with self._lock:
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            if job is None or job.owner != owner:
                raise LinkError(404, "That download is not available.")
            if job.stage in TERMINAL or job.stage == "queueing":
                raise LinkError(409, "That download has already finished or is already in Up Next.")
            job.cancel.set()
            if job.stage == "pending":
                self._change(job, stage="cancelled", error=guest_messages.DOWNLOAD_CANCELLED)
                self._save()

    def revoke(self, owners):
        with self._lock:
            for job in self._jobs.values():
                if job.owner in owners and job.stage not in TERMINAL and job.stage != "queueing":
                    job.cancel.set()
                    if job.stage == "pending":
                        self._change(job, stage="cancelled", error=guest_messages.ACCESS_REMOVED)
            self._save()

    def close(self):
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.stage not in TERMINAL and job.stage != "queueing":
                    job.cancel.set()
                    if job.stage == "pending":
                        self._change(job, stage="cancelled")
            self._save()
            if self._worker is None:
                self._release_journal()


def diagnostics_main(argv=None) -> int:
    """Explicit local executable probes. Does not start the sandbox or download."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Check local link acquisition prerequisites")
    parser.add_argument("--tools-only", action="store_true",
                        help="Check engine binaries without requiring an isolation launcher")
    parser.add_argument("--qualify", action="store_true",
                        help="Attack-test the configured launcher (IPv4/IPv6 loopback, LAN, "
                             "cloud metadata, home, leftover processes); saves the result for "
                             "this exact launcher file")
    parser.add_argument("--setup", action="store_true",
                        help="Install the reference launcher wrapper (Linux + bubblewrap) "
                             "and attack-test it; never enables a provider by itself")
    args = parser.parse_args(argv)
    setup_note = None
    if args.setup:
        import link_provision
        ok, setup_note = link_provision.install()
        if not ok:
            print(json.dumps({"setup": "unsupported_or_failed", "repair": setup_note}, indent=2))
            return 1
        args.qualify = True
    provider = CommandProvider()
    tools = {}
    for name, executable, flag in (
            ("yt-dlp", provider.tools["youtube"], "--version"),
            ("aria2c", provider.tools["magnet"], "--version"),
            ("ffprobe", provider.probe, "-version")):
        if executable is None:
            tools[name] = "missing"
            continue
        try:
            result = subprocess.run([executable, flag], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=5, check=False)
            tools[name] = "executable" if result.returncode == 0 else "probe_failed"
        except subprocess.TimeoutExpired:
            tools[name] = "probe_timed_out"
        except OSError:
            tools[name] = "probe_failed"
    ready = all(status == "executable" for status in tools.values())
    # Execute each engine *through* the launcher: a launcher that blocks
    # everything, or refuses an engine (the reference launcher refuses aria2c),
    # would pass an isolation-only probe yet could never download.
    engines = {}
    if provider.launcher:
        for name, executable in (("yt-dlp", provider.tools["youtube"]),
                                 ("aria2c", provider.tools["magnet"])):
            if executable is None:
                engines[name] = "missing"
                continue
            try:
                result = subprocess.run([provider.launcher, executable, "--version"],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=10, check=False)
                engines[name] = "executable" if result.returncode == 0 else "launcher_refused"
            except subprocess.TimeoutExpired:
                engines[name] = "probe_timed_out"
            except OSError:
                engines[name] = "probe_failed"
    qualification = None
    if args.qualify:
        import link_sandbox_probe
        qualification = link_sandbox_probe.qualify(provider.launcher)
        if provider.launcher:
            link_sandbox_probe.save(provider.launcher, qualification)
    report = {
        **({"setup_launcher": setup_note} if setup_note else {}),
        "tools": tools,
        "launcher_configured": bool(provider.launcher),
        **({"engines_via_launcher": engines} if provider.launcher else {}),
        "isolation_verified": bool(qualification.verified) if qualification else provider._isolation_verified(),
        **({"isolation_checks": qualification.checks, "isolation_detail": qualification.detail}
           if qualification else {}),
        "javascript_runtime_present": {
            name: bool(shutil.which(name)) for name in ("deno", "node", "qjs")},
        "notes": [
            "No network or media acquisition was attempted.",
            "The YouTube engine may also need a compatible JavaScript runtime and local EJS package.",
            "Executable presence does not prove supported versions or functioning downloads.",
            "An owner-configured isolation launcher is required; use --qualify to attack-test it.",
            "An engine that does not run through the launcher (refused, timed out or failed) cannot acquire that kind.",
            "Enable providers in Preferences only after qualifying the isolated worker.",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if qualification is not None and not qualification.verified:
        return 1
    return 0 if ready and (args.tools_only or provider.launcher) else 1


if __name__ == "__main__":
    raise SystemExit(diagnostics_main())
