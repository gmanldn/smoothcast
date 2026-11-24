"""Read-only SRT encoding detection and safe private UTF-8 staging.

Receiver and FFmpeg subtitle paths must reference staged UTF-8 data instead
of assuming that a user-provided .srt is UTF-8. No GTK or third-party modules.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import html
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import media_tools

MAX_SUBTITLE_BYTES = 16 * 1024 * 1024


class SubtitleEncodingError(ValueError):
    """Subtitle data is unreadable, unsafe or exceeds the staging limit."""


def decode_srt(data: bytes) -> tuple[bytes, str]:
    """Return validated UTF-8 SRT bytes and detected source encoding.

    Explicit BOMs take precedence; a strong NUL-position pattern identifies
    UTF-16 without a BOM. Otherwise prefer strict UTF-8, falling back to the
    common Windows-1252 encoding only when UTF-8 decoding fails. Do not
    silently replace undecodable characters.
    """
    if not data or len(data) > MAX_SUBTITLE_BYTES:
        raise SubtitleEncodingError("Subtitle file must be between 1 byte and 16 MiB")
    if data.startswith(b"\xef\xbb\xbf"):
        codec = "utf-8-sig"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        codec = "utf-16"
    else:
        sample = data[:256]
        even = sample[::2].count(0)
        odd = sample[1::2].count(0)
        if odd >= 4 and odd > even * 4:
            codec = "utf-16-le"
        elif even >= 4 and even > odd * 4:
            codec = "utf-16-be"
        else:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                codec = "cp1252"
            else:
                codec = "utf-8"
    try:
        text = data.decode(codec, errors="strict").lstrip("\ufeff")
    except UnicodeError as exc:
        raise SubtitleEncodingError("Unsupported or damaged SRT text encoding") from exc
    if not text or "-->" not in text:
        raise SubtitleEncodingError("Subtitle file has no SRT timestamp cues")
    if any(ord(ch) < 32 and ch not in "\t\r\n" for ch in text):
        raise SubtitleEncodingError("Subtitle contains binary/control characters")
    result = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    if not result or len(result) > MAX_SUBTITLE_BYTES:
        raise SubtitleEncodingError("Normalised subtitles exceed 16 MiB")
    return result, codec


def _read_regular(source: Path, limit: int) -> bytes:
    # O_NONBLOCK prevents a substituted FIFO from waiting for a writer.
    if source.is_symlink():
        raise SubtitleEncodingError("Subtitle source must be a regular file, not a symlink")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(os.open(source, flags), "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise SubtitleEncodingError("Subtitle source must be a regular file")
        if info.st_size == 0 or info.st_size > MAX_SUBTITLE_BYTES:
            raise SubtitleEncodingError("Subtitle file must be between 1 byte and 16 MiB")
        return handle.read(limit)


def cue_preview(source: Path) -> str:
    """Return a short plain-text sample from the first supported cue."""
    try:
        raw = _read_regular(source, 64 * 1024)
        if source.suffix.lower() == ".srt":
            raw, _ = decode_srt(raw)
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError, SubtitleEncodingError):
        return ""

    if source.suffix.lower() in {".ass", ".ssa"}:
        match = re.search(r"(?im)^Dialogue:[^\n]*", text)
        cue = match[0].split(",", 9)[-1] if match and match[0].count(",") >= 9 else ""
        cue = re.sub(r"\{[^}]*\}", "", cue).replace(r"\N", " ").replace(r"\n", " ")
    else:
        match = re.search(r"(?m)^\s*\d[\d:.,]+[ \t]+-->[^\n]*\n([^\n]+)", text)
        cue = match[1] if match else ""
    return " ".join(re.sub(r"<[^>]*>", "", cue).split())[:120]


def stage_srt(source: Path, destination: Path) -> tuple[Path, str]:
    """Atomically stage a private, UTF-8 encoded copy; never edit the source.

    Any decode/validation failure leaves an existing destination untouched.
    Creates mode 0600 temporary files in the destination directory and always
    removes those on error. Does not follow non-regular source files.
    """
    source = Path(source)
    destination = Path(destination)
    temporary: Path | None = None
    try:
        raw = _read_regular(source, MAX_SUBTITLE_BYTES + 1)
        normalised, codec = decode_srt(raw)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".smoothcast-srt-", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(normalised)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        temporary = None
        return destination, codec
    except OSError as exc:
        raise SubtitleEncodingError(f"Could not stage SRT captions: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# Scrub-time sidecar previews are parsed once in a worker, never on GTK motion.
# A compact immutable index makes every subsequent cue lookup logarithmic.
_CLOCK = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\Z")
_ASS_FORMAT = ("layer", "start", "end", "style", "name",
               "marginl", "marginr", "marginv", "effect", "text")
_PREVIEW_SUFFIXES = frozenset({".srt", ".vtt", ".ass", ".ssa"})


@dataclass(frozen=True)
class TimedCues:
    cues: tuple[tuple[float, float, str], ...] = ()
    starts: tuple[float, ...] = ()
    max_ends: tuple[float, ...] = ()


def _cue_time(value: str) -> float | None:
    match = _CLOCK.fullmatch(value.strip())
    if match is None:
        return None
    hours, minutes, seconds, fractional = match.groups()
    minute, second = int(minutes), int(seconds)
    if minute >= 60 or second >= 60:
        return None
    return int(hours or 0) * 3600 + minute * 60 + second + int(fractional.ljust(3, "0")) / 1000


def _caption_plain_text(value: str) -> str:
    """Strip ASS override tags and simple markup without interpreting HTML."""
    value = re.sub(r"\{[^{}]*\}", "", value)
    value = value.replace(r"\N", " ").replace(r"\n", " ")
    value = re.sub(r"<[^<>]*>", "", value)
    return " ".join(html.unescape(value).split())[:240]


def _parse_timed_cues(text: str, suffix: str) -> TimedCues:
    """Parse bounded UTF-8 subtitle text into a scrub-time cue index."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    items: list[tuple[float, float, str]] = []
    if suffix in {".ass", ".ssa"}:
        columns: tuple[str, ...] = _ASS_FORMAT
        in_events = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_events = stripped.casefold() == "[events]"
                continue
            if not in_events:
                continue
            if stripped.casefold().startswith("format:"):
                columns = tuple(key.strip().casefold() for key in stripped[7:].split(","))
                continue
            if not stripped.casefold().startswith("dialogue:"):
                continue
            # In ASS the final Text field may contain commas. Other layouts
            # cannot be parsed safely without a full grammar: skip them.
            if not columns or columns[-1] != "text" or not {"start", "end"} <= set(columns):
                continue
            values = stripped[9:].lstrip().split(",", len(columns) - 1)
            if len(values) != len(columns):
                continue
            start = _cue_time(values[columns.index("start")])
            end = _cue_time(values[columns.index("end")])
            caption = _caption_plain_text(values[-1])
            if start is not None and end is not None and end > start and caption:
                items.append((start, end, caption))
    else:
        for block in re.split(r"\n[ \t]*\n", text):
            lines = block.splitlines()
            marker = next((index for index, line in enumerate(lines[:3])
                           if "-->" in line), None)
            if marker is None:
                continue
            left, right = lines[marker].split("-->", 1)
            start = _cue_time(left)
            end = _cue_time(right.strip().split()[0]) if right.strip() else None
            caption = _caption_plain_text(" ".join(lines[marker + 1:]))
            if start is not None and end is not None and end > start and caption:
                items.append((start, end, caption))
    items.sort(key=lambda cue: (cue[0], cue[1]))
    starts: list[float] = []
    max_ends: list[float] = []
    maximum = 0.0
    for start, end, _text in items:
        starts.append(start)
        maximum = max(maximum, end)
        max_ends.append(maximum)
    return TimedCues(tuple(items), tuple(starts), tuple(max_ends))


def load_timed_cues(source: Path) -> TimedCues:
    """Build a safe sidecar cue index off-thread. No FFmpeg or receiver activity."""
    source = Path(source)
    if source.suffix.lower() not in _PREVIEW_SUFFIXES:
        raise SubtitleEncodingError("Unsupported timed subtitle preview format")
    raw = _read_regular(source, MAX_SUBTITLE_BYTES + 1)
    if source.suffix.lower() == ".srt":
        data, _encoding = decode_srt(raw)
        text = data.decode("utf-8")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    return _parse_timed_cues(text, source.suffix.lower())


def load_embedded_timed_cues(source: Path, subtitle_index: int) -> TimedCues:
    """Extract one embedded text track with bounded FFmpeg work, off-thread."""
    source = Path(source)
    if isinstance(subtitle_index, bool) or not isinstance(subtitle_index, int) or subtitle_index < 0:
        raise SubtitleEncodingError("Embedded subtitle track index is invalid")
    try:
        info = source.stat()
    except OSError as exc:
        raise SubtitleEncodingError("Embedded subtitle source is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SubtitleEncodingError("Embedded subtitle source must be a regular file")
    args = [media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(source), "-map", f"0:s:{subtitle_index}", "-c:s", "srt",
            "-fs", str(MAX_SUBTITLE_BYTES), "-f", "srt", "pipe:1"]
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=15, check=False)
    except FileNotFoundError as exc:
        raise SubtitleEncodingError("FFmpeg is unavailable for embedded subtitle preview") from exc
    except subprocess.TimeoutExpired as exc:
        raise SubtitleEncodingError("Embedded subtitle extraction timed out") from exc
    except OSError as exc:
        raise SubtitleEncodingError("Could not start embedded subtitle extraction") from exc
    if result.returncode != 0 or not result.stdout:
        raise SubtitleEncodingError("Embedded text track could not be extracted")
    if len(result.stdout) >= MAX_SUBTITLE_BYTES:
        raise SubtitleEncodingError("Embedded subtitle preview exceeds 16 MiB")
    try:
        text = result.stdout.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubtitleEncodingError("FFmpeg returned invalid subtitle text") from exc
    return _parse_timed_cues(text, ".srt")


def cue_at(cues: TimedCues, position: float) -> str:
    """Find the latest active caption, including overlapping forced cues."""
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        return ""
    if not math.isfinite(position) or position < 0:
        return ""
    index = bisect_right(cues.starts, position) - 1
    while index >= 0 and cues.max_ends[index] > position:
        start, end, caption = cues.cues[index]
        if start <= position < end:
            return caption
        index -= 1
    return ""
