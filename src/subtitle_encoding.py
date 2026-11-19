"""Read-only SRT encoding detection and safe private UTF-8 staging.

Receiver and FFmpeg subtitle paths must reference staged UTF-8 data instead
of assuming that a user-provided .srt is UTF-8. No GTK or third-party modules.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

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
        # Reject user-folder symlinks and do not follow them if an untrusted
        # file is replaced between the check and open. O_NONBLOCK prevents a
        # substituted FIFO from waiting indefinitely for a writer.
        if source.is_symlink():
            raise SubtitleEncodingError("Subtitle source must be a regular file, not a symlink")
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SubtitleEncodingError("Subtitle source must be a regular file")
            if info.st_size == 0 or info.st_size > MAX_SUBTITLE_BYTES:
                raise SubtitleEncodingError("Subtitle file must be between 1 byte and 16 MiB")
            raw = handle.read(MAX_SUBTITLE_BYTES + 1)
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
