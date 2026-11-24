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
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
from typing import Callable

MAX_LINK = 1500
MAX_BYTES = 2 * 1024**3
FREE_RESERVE = 512 * 1024**2
MAX_FILES = 128
MAX_PENDING = 4
MAX_RECORDS = 24
MAX_SECONDS = 1800
MEDIA_SUFFIXES = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ts",
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav",
})
TERMINAL = frozenset({"ready", "failed", "cancelled", "delivery_uncertain"})
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


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
                raise LinkError(413, "Torrent exceeds the 2 GiB acquisition limit.")
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
                raise LinkError(422, "Unsafe or excessive files in acquisition staging.")
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise LinkError(422, "Unsupported file in acquisition staging.")
    return total


def _safe_media(root: Path, path: Path) -> Path:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES
                or not path.resolve().is_relative_to(root.resolve())
                or path.suffix.lower() not in MEDIA_SUFFIXES):
            raise ValueError
    except (OSError, ValueError):
        raise LinkError(422, "The download did not produce a supported media file.") from None
    return path


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
        self.launcher = str(raw) if raw and Path(raw).is_absolute() and os.access(raw, os.X_OK) else ""
        self.tools = {kind: shutil.which(tool) for kind, tool in
                      (("youtube", "yt-dlp"), ("magnet", "aria2c"))}
        self.probe = shutil.which("ffprobe")
        self.kinds = frozenset(kinds)

    def capabilities(self) -> dict:
        return {kind: bool(kind in self.kinds and self.launcher and self.tools[kind] and self.probe)
                for kind in ("youtube", "magnet")}

    def _run(self, executable, args, directory, cancelled, progress, deadline):
        if cancelled():
            raise LinkError(409, "Acquisition cancelled.")
        if shutil.disk_usage(directory).free < FREE_RESERVE + MAX_BYTES:
            raise LinkError(507, "Not enough host disk space for a bounded acquisition.")
        command = [self.launcher, str(executable), *args]
        kwargs = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        except OSError:
            raise LinkError(503, "The configured acquisition worker could not start.") from None

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
                    raise LinkError(409, "Acquisition cancelled.")
                if time.monotonic() >= deadline:
                    raise LinkError(504, "The acquisition exceeded its time limit.")
                if _tree_bytes(directory) > MAX_BYTES or shutil.disk_usage(directory).free < FREE_RESERVE:
                    raise LinkError(507, "The host acquisition storage limit was reached.")
                time.sleep(0.25)
            if process.returncode:
                raise LinkError(502, "The external media worker failed or the source is unavailable.")
            if _tree_bytes(directory) > MAX_BYTES:
                raise LinkError(413, "Downloaded media exceeds the acquisition limit.")
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
            raise LinkError(503, "This host has not enabled an isolated worker for that source.")
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
            stage("downloading")
            progress(0, selected.size)
            self._run(tool, [*common, "--select-file=" + str(selected.index),
                             "--check-integrity=true", "--", str(clean)],
                      directory, cancelled, progress, deadline)
            path = _safe_media(directory, directory / selected.relative)
            if path.stat().st_size != selected.size:
                raise LinkError(422, "Torrent media size does not match verified metadata.")
        stage("verifying")
        if cancelled():
            raise LinkError(409, "Acquisition cancelled.")
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
    cancel: threading.Event = field(default_factory=threading.Event)


class LinkJobs:
    """One bounded worker per room; snapshots expose no URL, hash or path."""
    def __init__(self, root: Path, provider, deliver: Callable, owner_active: Callable):
        self.root = Path(root)
        self.provider = provider
        self.deliver = deliver
        self.owner_active = owner_active
        self._lock = threading.RLock()
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._revision = 0

    def capabilities(self):
        return self.provider.capabilities()

    def submit(self, owner: str, value: object, request: object) -> str:
        source = parse_link(value)
        if not isinstance(request, str) or not REQUEST_ID.fullmatch(request):
            raise LinkError(400, "Submission identifier is invalid.")
        if not self.owner_active(owner):
            raise LinkError(401, "Room access was revoked.")
        if not self.capabilities().get(source.kind):
            raise LinkError(503, "The host has not enabled this isolated acquisition worker.")
        with self._lock:
            if self._closed:
                raise LinkError(503, "The room is shutting down.")
            for job in self._jobs.values():
                if job.owner == owner and job.request == request:
                    if job.source != source:
                        raise LinkError(409, "Submission identifier was already used for another link.")
                    return job.id
                if job.source == source and job.stage not in {"failed", "cancelled"}:
                    return job.id
            if sum(j.stage not in TERMINAL for j in self._jobs.values()) >= MAX_PENDING:
                raise LinkError(429, "The room acquisition queue is full. Try again when a job finishes.")
            while len(self._jobs) >= MAX_RECORDS:
                expired = next((j for j in self._jobs.values() if j.stage in TERMINAL), None)
                if expired is None:
                    raise LinkError(429, "The room acquisition queue is full.")
                self._jobs.pop(expired.id)
            job = _Job(secrets.token_hex(12), owner, request, source, title=source.label)
            self._jobs[job.id] = job
            self._revision += 1
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="room-link-acquisition", daemon=True)
                self._worker.start()
            return job.id

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
                if job is None or self._closed:
                    self._worker = None
                    return
                self._change(job, stage="resolving")
            directory = self.root / job.id
            delivered = False

            def cancelled():
                return job.cancel.is_set() or not self.owner_active(job.owner)

            def stage(value):
                if cancelled():
                    raise LinkError(409, "Acquisition cancelled.")
                self._change(job, stage=value, received=None, total=None, rate=None, measured_at=0.0)

            try:
                if cancelled():
                    raise LinkError(409, "Acquisition cancelled.")
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                directory.mkdir(mode=0o700)
                path = self.provider.acquire(job.source, directory, stage,
                                             lambda n, total: self._progress(job, n, total), cancelled)
                path = _safe_media(directory, Path(path))
                if cancelled():
                    raise LinkError(409, "Acquisition cancelled.")
                # Keep the file if a dispatch may have happened. A lost
                # response must not remove media already in the queue.
                self._change(job, stage="queueing", title=path.name[:120],
                             received=path.stat().st_size, total=path.stat().st_size, rate=None)
                delivered = True
                self.deliver(job.owner, path)
                self._change(job, stage="ready")
            except LinkError as exc:
                self._change(job, stage="cancelled" if cancelled() and not delivered else
                             "delivery_uncertain" if delivered else "failed", error=exc.message, rate=None)
            except Exception:
                self._change(job, stage="delivery_uncertain" if delivered else
                             "cancelled" if cancelled() else "failed",
                             error="Queue delivery not confirmed; check Up Next." if delivered else
                             "Acquisition could not finish on this host.", rate=None)
            finally:
                if not delivered:
                    shutil.rmtree(directory, ignore_errors=True)

    def snapshot(self):
        with self._lock:
            return [{"id": j.id, "kind": j.source.kind, "title": j.title, "stage": j.stage,
                     "received": j.received, "total": j.total, "rate": j.rate, "error": j.error,
                     "executor": "room host"} for j in self._jobs.values()]

    def revision(self):
        with self._lock:
            return self._revision

    def cancel(self, owner, job_id):
        with self._lock:
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            if job is None or job.owner != owner:
                raise LinkError(404, "That acquisition is not available.")
            if job.stage in TERMINAL or job.stage == "queueing":
                raise LinkError(409, "The acquisition has already finished or is entering Up Next.")
            job.cancel.set()
            if job.stage == "pending":
                self._change(job, stage="cancelled", error="Acquisition cancelled.")

    def revoke(self, owners):
        with self._lock:
            for job in self._jobs.values():
                if job.owner in owners and job.stage not in TERMINAL and job.stage != "queueing":
                    job.cancel.set()
                    if job.stage == "pending":
                        self._change(job, stage="cancelled", error="Room access was revoked.")

    def close(self):
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.stage not in TERMINAL and job.stage != "queueing":
                    job.cancel.set()
                    if job.stage == "pending":
                        self._change(job, stage="cancelled")
